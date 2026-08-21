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
agent suite implicitly.

For the usual remote workflow, install the T3 Code desktop or mobile client
on the device you will use and select only `--web-interface t3code` on the VM.
Use `--desktop-interface t3code` only when the VM itself should also provide a
local graphical/RDP T3 Code session.

## Headless VM setup

For a private LAN workflow, use a source CIDR. The source option automatically
changes the default bind from loopback to all IPv4 interfaces and adds a UFW
rule for only the requested network:

```bash
infra-tools setup server_dev 192.168.0.41 agent \
  --agent-tool gh \
  --agent-tool codex \
  --agent-tool opencode \
  --web-interface t3code \
  --web-interface-source 192.168.0.0/24 \
  --device-pairing t3code \
  --device-pairing-auth-file /run/secrets/agent-1-pairing.htpasswd \
  --agent-workspace /srv/agent-workspace \
  --git-access read
```

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

Without `--web-interface-source`, the service binds to `127.0.0.1`. This is a
good default for an SSH tunnel:

```bash
ssh -N -L 3773:127.0.0.1:3773 agent@192.168.0.41
```

The generated service is `infra-tools-t3code.service`:

```bash
sudo systemctl status infra-tools-t3code.service
sudo journalctl -u infra-tools-t3code.service -n 100 --no-pager
```

The service wrapper explicitly adds the T3 runtime, setup user's `~/.local/bin`,
and `~/.opencode/bin` directories to `PATH`. This is required because systemd
does not load the user's interactive shell startup files, and it lets the
service discover user-scoped T3, Codex, Claude Code, and OpenCode
installations.

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

## Pair a client or browser

The bare service address is intentionally not an authenticated web session. If
you browse to `http://192.168.0.41:3773/`, T3 Code will show a field for a
pairing key. That is expected: the pairing key is the one-time authentication
step, not a setup failure. Do not remove pairing or publish the bare endpoint.

With `--device-pairing t3code`, visit the protected enrollment portal from an
allowed LAN device:

```text
http://192.168.0.41:3774/
```

After the Nginx Basic Auth prompt, **Create a link for this browser** creates a
ten-minute, one-time T3 credential and displays a button that opens the
authenticated T3 session. The explicit second click avoids browser-dependent
cross-port redirect behavior. **Create a link for another T3 client** displays
a link that can be copied into the desktop or mobile client. New devices
therefore do not require terminal access at enrollment time.

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
The command runs the target user's `t3code-pair` helper over SSH and prints
T3's one-time URL, token, and QR information. Use the complete pairing URL in
the T3 Code desktop or mobile client, or scan the QR code where supported. For
a browser, open the complete direct LAN pairing URL from that output—not the
bare service address—and then add the VM projects from T3's normal project
picker. Treat the URL and token as passwords.

The equivalent target-side command is:

```bash
t3code-pair
```

After pairing, use T3's authentication commands to inspect or revoke sessions:

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
Add Environment. A numeric private-network address uses HTTP for direct LAN
access; use an explicit `https://` address only after configuring an HTTPS
endpoint.

The direct LAN workflow and its optional Basic Auth enrollment portal use HTTP
and are intended only for a trusted private network. Basic Auth is not
transport encryption. Direct T3 desktop/mobile clients can use the T3
endpoint. A browser page served over HTTPS, including `https://app.t3.codes`,
cannot connect to a plain HTTP/WebSocket backend because of mixed-content
restrictions. For that workflow, put the service behind an HTTPS reverse proxy
or an HTTPS tailnet endpoint and pair with the resulting `https://` URL.
infra-tools currently does not create that public reverse-proxy exposure
automatically; keep the backend private until TLS, WebSocket proxying, and any
desired outer access control are configured.

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

T3's browser-facing client is separate from infra-tools' browser automation
capability. Add `--browser-automation playwright` when Codex/OpenCode need a
managed Playwright browser for previews and interaction; T3 itself does not
turn a VM into a public web-preview host.

## References

- [T3 Code remote access](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md)
- [T3 Code background service](https://github.com/pingdotgg/t3code/blob/main/docs/user/background-service.md)
- [T3 Code installation and provider discovery](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md)
