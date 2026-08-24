# T3 Code interfaces

T3 Code has two explicit deployment targets:

- `--desktop-interface t3code` installs the Linux desktop application for a
  local console or RDP session.
- `--web-interface t3code` installs T3 Code's headless server on the VM. A
  desktop or mobile T3 Code client, or a browser on the local network, then
  connects to that server.

Both modes use the provider CLIs and their credentials on the VM. The client
device does not need the VM's Codex, Claude Code, or OpenCode credentials.
Select at least one provider explicitly; infra-tools does not install an
agent suite implicitly unless the `--t3code-ready` preset is selected.

For a headless VM that should be ready for remote T3 use, the shorthand
`--t3code-ready` selects GitHub CLI, Codex, read-write Git, the T3 web service,
and protected device pairing. It does not copy credentials automatically;
provide the explicit Git and agent authentication options when credentials
should be staged.

For the usual remote workflow, install the T3 Code desktop or mobile client
on the device you will use and select only `--web-interface t3code` on the VM.
Use `--desktop-interface t3code` only when the VM itself should also provide a
local graphical/RDP T3 Code session.

## Headless VM setup

For a private LAN workflow, use the generic LAN preset. It automatically
changes the default bind from loopback to all IPv4 interfaces and adds UFW
rules for the RFC 1918 IPv4 ranges and IPv6 ULA:

```bash
infra-tools setup server_dev 192.168.0.41 agent \
  --agent-tool gh \
  --agent-tool codex \
  --agent-tool opencode \
  --web-interface t3code \
  --lan-access \
  --device-pairing t3code \
  --device-pairing-auth-file /run/secrets/agent-1-pairing.htpasswd \
  --agent-workspace /srv/agent-workspace \
  --git-access read
```

The equivalent minimal ready profile is:

```bash
infra-tools setup server_dev 192.168.0.41 agent --t3code-ready
```

Add `--lan-access` when another device should reach the VM directly. Without
an access source, T3 remains loopback-only and can be reached through SSH or a
managed HTTPS forward.

T3 Code also enables the Node.js runtime automatically because its headless
CLI requires Node. The service runs as the setup user, starts at boot, and
uses `/srv/agent-workspace` as its working directory. If no workspace is
specified, it uses `~/repos`. The generated systemd unit waits for both the
account's home path and workspace path to be mounted before starting, so a
separate data disk can safely host either agent state or the workspace.

The current T3 Code server requires a compatible Node.js release (currently
`^22.16 || ^23.11 || >=24.10`) and at least one authenticated provider CLI on
the VM. infra-tools installs the selected provider CLIs and its Node LTS
runtime; authentication remains an explicit credential setup step.

Use `--access-source 192.168.0.0/24 100.64.0.0/10` when the preset is broader
than desired. `--web-interface-source` remains available for sources that
should reach only T3 Code and is combined with generic sources. Without either
kind of source, the service binds to `127.0.0.1`. This is a good default for an
SSH tunnel:

```bash
ssh -N -L 3773:127.0.0.1:3773 agent@192.168.0.41
```

The generated service is `infra-tools-t3code.service`:

```bash
sudo systemctl status infra-tools-t3code.service
sudo journalctl -u infra-tools-t3code.service -n 100 --no-pager
```

The service wrapper explicitly adds the T3 runtime, setup user's `~/.local/bin`,
`~/.opencode/bin`, and the standard system executable directories to `PATH`.
This is required because systemd does not load the user's interactive shell
startup files. It lets the service discover user-scoped T3, Codex, Claude Code,
and OpenCode installations as well as system packages such as GitHub CLI. The
wrapper also sets `GH_CONFIG_DIR` to the managed `~/.config/gh` directory, so
T3 invokes the real system `gh` binary with the same credentials as the target
user's terminal. The compatibility shim previously used for T3 discovery is no
longer installed; use the upstream T3 release and the readiness doctor when
diagnosing provider issues.

During setup, infra-tools installs `build-essential` and `python3`, then
installs T3 and its native dependencies as the target user under
`~/.local/share/infra-tools/t3code`. T3's `node-pty` dependency may need to
compile on Linux, and npm install scripts are explicitly enabled for this
isolated VM-local runtime. The service executes that installed binary directly;
it does not run `npx`, download packages, or rebuild native modules at every
boot. A normal setup rerun verifies the persistent runtime and repairs it only
when unhealthy; pass `--refresh-packages` when you deliberately want to
refresh T3 and the other versioned runtimes.

Normal service output is not placed in the journal because startup output can
contain pairing material. Errors remain in the journal. When device pairing is
selected, a separate `infra-tools-device-pairing.service` runs a generic local
broker over a Unix socket and Nginx exposes its Basic-Auth-protected enrollment
page on port `3774` by default.
The broker is ordered after T3 at boot but is intentionally not stopped when the
T3 service is restarted. This keeps the enrollment page available while a
successful T3 Connect authorization applies the new relay state.

Setup prints the service endpoint and the readiness command. Run the latter as
the target user after authentication or a service change:

```bash
infra-tools agent doctor --capability t3code
infra-tools agent doctor --capability t3code --fix
```

The diagnostic checks the service, runtime, pairing helper, local endpoint,
GitHub authentication, Git identity and credential helper, and the managed
T3 agent skill. `--fix` only configures the GitHub HTTPS helper after a valid
`gh` login and restarts an inactive managed service.

## Pair a client or browser

The bare service address is intentionally not an authenticated web session. Use
the **T3 Code HTTPS endpoint printed by setup**. T3 Code will show a field for
a pairing key. That is expected: the pairing key is the one-time
authentication step, not a setup failure. Do not remove pairing or publish the
bare endpoint. The direct `3773` listener remains HTTP-only for compatibility;
do not prepend `https://` to it.

With `--device-pairing t3code`, open the **T3 Code pairing HTTPS endpoint
printed by setup** from an allowed LAN device. The direct `3774` listener is
HTTP-only compatibility and is not an HTTPS endpoint:

```text
http://192.168.0.41:3774/
```

After the Nginx Basic Auth prompt, **Create a link for this browser** creates a
short-lived, one-time administrative T3 credential and displays a button that
opens the authenticated T3 session. The explicit second click avoids
browser-dependent cross-port redirect behavior. **Create a link for another T3
client** displays a link that can be copied into the desktop or mobile client.
New devices therefore do not require terminal access at enrollment time.

Administrative enrollment is intentional for the VM owner's app: in addition
to normal project, agent, terminal, and review capabilities, the resulting
session has T3's `access:read` and `access:write` scopes. Settings → Connections
can therefore create pairing links, inspect authorized clients, and revoke
sessions. T3 does not upgrade a previously paired standard session in place;
if that page reports that administrative access is unavailable, remove the
saved environment from the client and pair it again with a newly issued
infra-tools link.

The pairing portal is separate from T3's port. Basic Auth protects credential
issuance; T3's native pairing exchange and per-device session protect the
actual agent service. This keeps ordinary desktop and mobile clients compatible
with the direct T3 endpoint. See [Protected device pairing](DEVICE_PAIRING.md)
for password-file creation, rotation, removal, and the plaintext-LAN security
boundary.

Without the portal, or for recovery, obtain a fresh pairing URL from the
control system without opening an interactive VM shell:

```bash
infra-tools agent web pair 192.168.0.41 agent
```

Add `--key /path/to/ssh_key` when the saved SSH identity is not the default.
The command runs the target user's `t3code-pair` helper over SSH and prints an
administrative one-time URL. Use the complete pairing URL in the T3 Code
desktop or mobile client. For a browser, open the complete direct LAN pairing
URL from that output—not the bare service address—and then add the VM projects
from T3's normal project picker. Treat the URL and token as passwords.

The equivalent target-side command is:

```bash
t3code-pair
```

The helper briefly issues a two-minute administrative bearer session through
T3's supported CLI, uses it only against the VM-local T3 API to delegate a
one-time administrative pairing credential, and immediately revokes the
temporary session. Neither credential is saved by infra-tools or written to
the service journal. After pairing, use T3's authentication commands to inspect
or revoke sessions:

```bash
t3 auth --help
```

The T3 runtime is already installed in the target user's persistent
`~/.local/share/infra-tools/t3code` directory, and its bin directory is on the
login user's PATH. Do not use `npx` for T3 administration, since that can
select a different version or recreate the native-module problem described
above.

For a desktop client, the normal choices are:

- enter the full pairing URL in the client after running `infra-tools agent web pair`;
- use the direct LAN endpoint from a client that can reach the VM; or
- use the client's SSH remote-environment flow when you prefer not to expose a
  LAN port. The SSH flow forwards the VM's loopback service and still leaves
  projects, provider sessions, and Git credentials on the VM.

For a mobile client, use the pairing URL/QR code or enter the VM address in
Add Environment. T3 web setup configures an internal HTTPS forward for the web
and pairing pages by default. Use the HTTPS URL printed by setup when
connecting from a browser or another client that supports HTTPS.

The direct LAN workflow remains available over HTTP as a compatibility path and
is intended only for a trusted private network. Basic Auth is not transport
encryption. Prefer the managed HTTPS endpoints for T3 desktop/mobile clients
and browser pages, including `https://app.t3.codes`; they provide WebSocket
support without mixed-content failures. T3 web setup creates managed HTTPS
reverse-proxy forwards with the same source policy:

```bash
sudo infra-web forward add t3code --listen auto --to 127.0.0.1:3773
```

Use the resulting HTTPS origin as the browser endpoint. The pairing portal is
published through a second managed HTTPS forward when device pairing is
enabled. The VM-local CA is available from the internal-web landing page for
LAN clients that do not already trust it.

The pairing portal's T3 Connect section runs `t3 connect link --headless`,
accepts the relay-install and authorization prompts, and requests a restart of
the managed T3 service. Its checkbox maps to T3's persisted desired Connect
state; applying an already-enabled checkbox preserves that state, while
clearing it runs `t3 connect unlink`. Use **Refresh status** to see new prompt
output without interrupting text entry.

When generating the app enrollment link over SSH, pass that HTTPS origin to
the target-side helper so the app receives the externally reachable address:

```bash
t3code-pair --base-url https://HOST:PORT
```

T3's native pairing remains the service authentication boundary. CIDR firewall
rules limit which machines can reach the endpoint, but they do not replace
pairing. The optional Basic Auth layer protects only infra-tools' separate
credential-issuance portal; it is not placed in front of T3's API/WebSocket
endpoint and does not replace or revoke T3 sessions.

## Desktop installation

Install the desktop interface on a desktop-capable target with the provider
CLIs it should use:

```bash
infra-tools setup workstation_dev 192.168.0.42 agent \
  --agent-tool codex \
  --agent-tool opencode \
  --desktop-interface t3code \
  --rdp --rdp-source 192.168.0.0/24
```

The official x86_64 Linux AppImage is checksum-verified, installed under the
agent user's home, and registered with the desktop menu. This is independent
of `--web-interface`; a target may select both when it should support local
RDP use and remote clients.

The desktop AppImage is not required for the separate desktop-client workflow
described above. It is installed on the VM only for local GUI use.

## Provider and repository behavior

The T3 server must run on the VM where the provider CLIs, Git credentials, and
repositories are available. Use `--git-access read` or `read-write` and the
credential options described in [CREDENTIALS.md](CREDENTIALS.md). Public HTTPS
repositories can be cloned without credentials. Use `--repo` and
`--agent-workspace` for initial checkout, or create projects on the VM as the
target user.

T3's **GitHub repository** source accepts `owner/repo`. As a simpler path that
bypasses provider lookup entirely, select **Git URL** and enter the canonical
HTTPS URL, such as `https://github.com/owner/repo.git`. Private GitHub URLs use
the same target-user credential helper installed by `gh auth setup-git`; no
token should be embedded in the URL.

T3's browser-facing client is separate from infra-tools' browser automation
capability. Add `--browser-automation playwright` when Codex/OpenCode need a
managed Playwright browser for previews and interaction; T3 itself does not
turn a VM into a public web-preview host.

## References

- [T3 Code remote access](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md)
- [T3 Code background service](https://github.com/pingdotgg/t3code/blob/main/docs/user/background-service.md)
- [T3 Code installation and provider discovery](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md)
