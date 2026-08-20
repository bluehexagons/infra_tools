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

The service wrapper explicitly adds the setup user's `~/.local/bin` and
`~/.opencode/bin` directories to `PATH`. This is required because systemd does
not load the user's interactive shell startup files, and it lets the service
discover user-scoped Codex, Claude Code, and OpenCode installations.

Normal service output is not placed in the journal because startup output can
contain pairing material. Errors remain in the journal.

## Pair a client

After setup, SSH to the VM as the agent user and run:

```bash
t3code-pair
```

The helper uses the same Node/T3 environment as the service and prints a
one-time pairing URL and token. Use the full URL in the T3 Code desktop or
mobile client, or scan the QR code where supported. Treat the URL and token as
passwords. After pairing, use T3's authentication commands to inspect or
revoke sessions:

```bash
npx t3 auth --help
```

For a desktop client, the normal choices are:

- enter the full pairing URL in the client after running `t3code-pair`;
- use the direct LAN endpoint from a client that can reach the VM; or
- use the client's SSH remote-environment flow when you prefer not to expose a
  LAN port. The SSH flow forwards the VM's loopback service and still leaves
  projects, provider sessions, and Git credentials on the VM.

For a mobile client, use the pairing URL/QR code or enter the VM address in
Add Environment. A numeric private-network address uses HTTP for direct LAN
access; use an explicit `https://` address only after configuring an HTTPS
endpoint.

The direct LAN workflow uses HTTP and is intended only for a trusted private
network. Direct T3 desktop/mobile clients can use this endpoint. A browser
page served over HTTPS, including `https://app.t3.codes`, cannot connect to a
plain HTTP/WebSocket backend because of mixed-content restrictions. For that
workflow, put the service behind an HTTPS reverse proxy or an HTTPS tailnet
endpoint and pair with the resulting `https://` URL. infra-tools currently
does not create that public reverse-proxy exposure automatically; keep the
backend private until TLS, WebSocket proxying, and any desired outer access
control are configured.

T3's native pairing is the authentication boundary. CIDR firewall rules limit
which machines can reach the endpoint, but they do not replace pairing. An
HTTP Basic Auth layer can be added at a future reverse-proxy boundary; it is
not used by the direct service because it would not replace T3's own session
authentication.

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
