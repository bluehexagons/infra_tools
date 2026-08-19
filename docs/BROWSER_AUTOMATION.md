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
  --agent-tool gh --agent-tool codex --agent-tool opencode \
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
For an explicit `--steps` setup, include `install_browser_automation` after
installing the selected compatible agent; it is available as a registered
custom step as well.

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

The MCP launcher always starts Chromium in headless, isolated mode. Each MCP
connection receives a temporary browser profile; cookies and login state do not
persist between sessions. This avoids profile locking between simultaneous
agents and prevents one task from silently inheriting another task's browser
session. Use the normal desktop browser over RDP when a durable, human-managed
browser profile is required.

## What agents can do

Once provisioned, Codex or OpenCode can ask the `infra-tools-playwright` MCP server to open
pages, inspect rendered content, click controls, fill forms, and capture
screenshots. Browser traffic originates from the VM and is subject to its DNS,
routing, firewall, proxy, and destination-site controls. The provisioning smoke
test does not require internet access: it launches Chromium, interacts with a
local in-memory page, verifies rendering, and closes the browser.

Website authentication is deliberately not part of infra-tools credential
copying. Supply site-specific credentials through the application or a scoped
secret workflow appropriate to the task; do not put passwords or session tokens
in setup commands, repository files, prompts intended for logging, or agent
configuration. Isolated mode discards any cookies created during the session.

## Verification

Run the browser check on the configured VM as the setup user:

```bash
infra-tools agent doctor \
  --tool codex --tool opencode \
  --capability browser
```

Add `--json` for automation. The capability is healthy only when both managed
launchers are executable, every installed compatible agent has the managed MCP
registration, and the local interaction/rendering smoke test passes. If only
one compatible agent was provisioned, list only that tool. The default doctor
tool set still includes all terminal agents, so explicit `--tool` flags are
useful on deliberately minimal VMs.

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
