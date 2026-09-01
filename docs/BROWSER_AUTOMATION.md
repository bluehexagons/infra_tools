# Agent browser automation

infra-tools can provision a browser that Codex and OpenCode use directly from
their agent sessions. This is separate from the workstation browser selected
with `--browser`: agent automation uses a pinned Playwright MCP package and its
matching Chromium build, while `--browser` installs an interactive desktop or
terminal browser for a person.

## Provisioning

Select at least one compatible agent and request the provider explicitly:

```bash
infra-tools setup workstation_dev 192.168.0.41 agent \
  --provision-on ts1 --name agent-1 \
  --image-storage ts1-storage \
  --memory 4G --balloon-min 1G --storage root ts1-storage 32G \
  --agent-tool opencode,gh,codex \
  --browser-automation playwright \
  --node --go --rdp --password "$RDP_PASSWORD" \
  --rdp-source 192.168.0.0/24 --rdp-source 10.0.0.0/8
```

`--browser-automation playwright` currently requires `--agent-tool codex`
or `--agent-tool opencode`. It registers the managed
`infra-tools-playwright` MCP server
only for the compatible tools selected by that setup. GitHub CLI, Claude Code,
and T3 Code do not receive a browser integration. The browser capability owns
its system Node.js dependency, so `--node` is not required unless projects on
the VM also need the user-managed Node.js development environment.

The interactive setup flow offers the same choice after agent selection. A
saved setup command retains the provider choice, so a later full setup restores
the browser capability without retaining any browser or website credentials.
An agent setup that omits the option also refreshes launchers for a complete
existing managed browser installation; this keeps safety defaults current when
the controller updates the target source independently of optional capability
selection. An explicit `--no-browser-automation` suppresses that reconciliation.
For an explicit `--steps` setup, include `install_browser_automation` after
installing the selected compatible agent; it is available as a registered
custom step as well.

Compatible agent setups also install the `infra-tools-browser-testing` skill.
It routes between T3's collaborative preview and this optional VM-local
fallback; see [Managed agent workflow skills](AGENT_SKILLS.md).

## Installed components and agent configuration

Setup installs the exact Playwright MCP version declared by infra-tools under
`/opt/infra-tools-playwright`, verifies the npm package version and registry
integrity metadata, installs native browser dependencies, and downloads the
matching Chromium build into the target user's Playwright cache. npm lifecycle
scripts are disabled during the root-owned package install.

The managed launchers are:

- `/usr/local/bin/infra-tools-playwright-mcp` for MCP clients;
- `/usr/local/bin/infra-tools-playwright-doctor` for a local smoke test.

Codex registration is performed through `codex mcp`; OpenCode's existing JSON
or JSONC configuration is merged atomically. JSONC comments and formatting are
normalized during the rewrite, while configuration values are preserved. If
`--agent-config active` copied a config,
the browser registration is applied afterward, so the explicit setup choice
owns the `infra-tools-playwright` entry while preserving unrelated settings and
MCP servers.
Malformed or symlinked target configuration is rejected.

The MCP launcher resolves the Chromium executable from the same pinned
Playwright package used to provision the user browser cache and passes that
path explicitly to MCP. It does not rely on MCP's default Chrome channel. The
launcher always starts Chromium in headless, isolated mode and enables
Playwright's bounded vision capability. Each MCP
connection receives a temporary browser profile; cookies and login state do not
persist between sessions. This avoids profile locking between simultaneous
agents and prevents one task from silently inheriting another task's browser
session. Use the normal desktop browser over RDP when a durable, human-managed
browser profile is required.

Generated snapshots, console captures, screenshots, and other MCP evidence
default to the private
`~/.local/state/infra_tools/playwright-mcp` directory instead of the current
project. The launcher applies a 256 MiB output ceiling so older evidence is
evicted without dirtying or filling active Git worktrees. An agent may still
name an explicit output file when the evidence belongs in a requested
deliverable. Omit `filename` for routine evidence: Playwright resolves unnamed
artifacts below the private output directory and returns their paths, while an
explicit name deliberately resolves in the active workspace.

## What agents can do

Once provisioned, Codex or OpenCode can ask the `infra-tools-playwright` MCP server to open
pages, inspect rendered content, click controls, fill forms, and capture
screenshots. The vision tools include safe viewport-coordinate mouse input for
canvas applications that expose no internal DOM controls, avoiding unrestricted
code evaluation for ordinary canvas clicks. Browser traffic originates from
the VM and is subject to its DNS,
routing, firewall, proxy, and destination-site controls. The provisioning smoke
test does not require internet access: it launches Chromium, interacts with a
local in-memory page, verifies rendering, and closes the browser. The doctor
allows slow browser operations up to two minutes, with a three-minute hard
process limit, so a cold browser can complete while a small ballooned VM is
temporarily swapping. Exceeding that limit reports likely memory, swap, or
storage pressure instead of an ambiguous locator timeout.

Managed actions settle for one second before returning, which gives WebGL
canvases more time to present a complete frame after input. A still-empty
capture should be retried once after another short wait. Chromium GPU capture
messages such as `ReadPixels` warnings are browser-process diagnostics; use the
browser console tool to determine whether the page itself logged warnings or
errors.

Website authentication is deliberately not part of infra-tools credential
copying. Supply site-specific credentials through the application or a scoped
secret workflow appropriate to the task; do not put passwords or session tokens
in setup commands, repository files, prompts intended for logging, or agent
configuration. Isolated mode discards any cookies created during the session.

## Collaborative preview and private networks

T3 Code's collaborative preview and the managed Playwright fallback do not use
the same network origin. The collaborative browser runs in the connected
client's context, while managed Playwright runs on the agent VM. Consequently,
an internal `infra-web` URL such as `https://192.168.x.x:8443/...` can pass
`curl` and `infra-web doctor` on the VM yet fail in the collaborative preview
when the client lacks a route to that LAN, is outside the gateway's allowed
source ranges, or has not enrolled the local CA.

An `environment-port` preview target is a host rewrite, not a tunnel from the
connected client to VM loopback. T3 maps the requested port onto the host in
the environment connection. If that connection is represented by localhost,
the collaborative browser still requests its own localhost; if it is
represented by a private VM address, a server bound only to VM loopback is not
listening on that address. A healthy loopback Vite server can therefore remain
unreachable through both `environment-port` and a direct loopback URL. Treat a
failed navigation that leaves the tab at `about:blank` with no network request
as a client/VM routing boundary after verifying the VM endpoint. Do not rebind
the development server or widen firewall policy solely for automation; use
the managed VM-local fallback, or use an explicit `infra-web` publication when
client access is part of the task.

Collaborative preview is an opportunistic test surface. During normal agent
work, T3 may be minimized, its preview pane may be closed, or no preview
automation host may be attached. These are expected coverage states, not
application-health failures and not reasons to pause unrelated implementation
or non-browser verification.

Agents should call preview status first and open a preview once when no
automation-capable tab is attached. A tab with `visible: false` may still
navigate and accept input, but a minimized T3 window can make snapshots or
recordings fail. Attempt one snapshot after navigation. If capture fails or
times out while the tab remains available and invisible, do not repeatedly
retry or diagnose the application, WebGL, TLS, or network from that result.
Use the healthy VM-local fallback when its different network origin is
appropriate, or finish with non-browser checks and report the coverage gap.
When collaborative evidence is important, restoring T3 should make the
existing tab capturable; recheck status and retry that tab rather than opening
duplicates.

For WebAssembly and WebGL applications, successful browser navigation can
precede runtime initialization. A snapshot containing only a splash screen or
progress bar confirms document rendering but not application readiness. Wait
one bounded startup interval and capture the expected application frame once;
do not turn ordinary runtime startup into an unbounded polling loop.

An opened preview tab or a status result containing the requested URL does not
prove the document rendered. Confirm a snapshot or user-visible content. When
private-URL navigation fails, separate the failure layers:

1. verify the exact URL and a non-sensitive artifact from the VM with normal
   TLS verification;
2. if preview status remains available, inspect a snapshot and its network
   error before treating a generic navigation failure as a detached preview;
3. check whether the client reports a certificate error, as opposed to a
   timeout or unreachable route;
4. use `infra-web ca` only for explicit client certificate trust errors, then
   follow [Client CA trust](CLIENT_CA_TRUST.md) for fingerprint verification
   and Linux, Windows, ChromeOS, or Android enrollment;
5. use the explicitly provisioned VM-local browser when a VM-origin rendering
   check is appropriate and the current agent integration permits it.

When T3 reports that no preview automation host is available, run
`infra-tools agent doctor --capability browser --json` as the explicit fallback
probe. This is a handoff to a separate VM-origin browser, not evidence that the
application or collaborative preview URL is unhealthy. If that optional
capability is absent or unhealthy, continue with safe non-browser checks and
state what browser coverage could not be collected; do not install a separate
automation stack ad hoc.

A client-only reachability failure is not evidence that the hosted site is
down. Do not respond by weakening TLS, expanding gateway/firewall exposure, or
rebinding the application. Report which network origin passed and which one
failed so the operator can decide whether that client should have access.

## Verification

Run the browser check on the configured VM as the setup user:

```bash
infra-tools agent doctor \
  --tool codex --tool opencode \
  --capability browser
```

Add `--json` for automation. The capability is healthy only when both managed
launchers are executable, root-owned regular files without group or world write
access; explicit managed-Chromium selection and current private, bounded
evidence, safe-coordinate, and one-second-settle defaults are present; every
installed compatible agent has the managed MCP
registration; active managed MCP processes use those same safe defaults; and
the local interaction/rendering smoke test passes. A stale or unsafe launcher
is unhealthy even when its smoke test passes; inspect an unsafe path, then
rerun the saved setup to reconcile it. A stale active process instead requires
restarting the agent session that owns it. If only one compatible agent was
provisioned, list only that tool. The default doctor tool set still includes
all terminal agents, so explicit `--tool` flags are useful on deliberately
minimal VMs.

JSON results include a stable `issues` list and one primary `remediation` code.
`mcp_browser_selection_missing` identifies a launcher that can pass the direct
Chromium smoke test while MCP still defaults to an unavailable Chrome channel;
`rerun_saved_setup` refreshes stale managed defaults;
`rerun_setup_with_browser_automation` restores missing launchers or agent
registration; `inspect_launcher_security_then_rerun_saved_setup` requires
reviewing an unsafe managed path before reconciliation;
`restart_agent_sessions` identifies MCP processes that were started before a
launcher or trust-store update and must be restarted rather than reconfigured;
and `inspect_browser_runtime` identifies an installation whose local Chromium
smoke test failed. These fields are also retained in redacted readiness records
and support bundles.

For lower-level checks:

```bash
/usr/local/bin/infra-tools-playwright-doctor
codex mcp list
```

Inspect `~/.config/opencode/opencode.json` or `opencode.jsonc` for OpenCode's
`mcp.infra-tools-playwright` entry. The managed OpenCode entry uses a 30-second tool
discovery timeout to accommodate cold VM startup. Do not print agent auth files
while troubleshooting.

## Security and operating limits

Browser automation is not a security boundary. A page can contain untrusted
content designed to influence an agent, and a browser-enabled agent can act
with the network access, repository access, and application credentials
available to its Unix user. Prefer scoped repository and website credentials,
restrict VM egress where appropriate, and require human review for sensitive
or irreversible actions.

The managed server uses local stdio rather than an exposed network listener.
Chromium retains its browser sandbox; VM targets are recommended. Browser
namespaces and sandboxes may not work in every container policy, so use a VM
when browser automation must be reproducible. Rerunning setup reconciles the
managed registration and package version. Version changes are delivered through
an infra-tools update and should be reviewed like other executable dependency
updates.
