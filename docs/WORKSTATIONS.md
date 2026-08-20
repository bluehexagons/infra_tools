# Workstations and desktop applications

The workstation system types build a Debian desktop from the same
machine-aware setup pipeline used for servers. Choose a profile first, then
override the desktop, browser, or application choices with flags.

To use a Debian desktop as the local control plane, combine the workstation
profile with `--control-plane` and select the agent tools you need (GitHub CLI
and Codex CLI in this example):

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --local-setup workstation_dev \
  --control-plane --agent-tool gh --agent-tool codex --desktop xfce --rdp --rdp-existing-password
rm -f "$HOME/.infra_tools-install.sh"
```

This keeps the graphical workstation setup while adding the SSH, rsync,
diagnostic, terminal, and package-management tools used to administer other
VMs and containers. It assumes the standard Debian GNOME desktop and existing
local account password: GNOME remains the console desktop, while XFCE is used
for XRDP sessions. Select only the graphical agents needed with repeatable
`--agent-tool` flags; language runtimes remain separate explicit options.

Agent installation, authentication, and non-secret configuration are separate
choices. See [Credentials and agent configuration](CREDENTIALS.md) before
copying active-user credentials to a workstation or VM, especially when
multiple VMs need independent GitHub access.
For agent-controlled page previews and interaction, see
[Agent browser automation](BROWSER_AUTOMATION.md); it is independent of the
human-operated browser described in this guide.

T3 Code's desktop AppImage is selected with `--desktop-interface t3code`.
The headless service is a separate `--web-interface t3code` choice; it is
documented in [T3_CODE.md](T3_CODE.md) and can be selected alongside the
desktop interface when both local RDP and remote clients are useful.

## Profiles

| Profile | Adds by default |
| --- | --- |
| `workstation_desktop` | Desktop, CLI tools, browser, and Discord |
| `pc_dev` | Desktop, browser, LibreOffice, SMB client packages, Remmina, and Discord |
| `workstation_dev` | Desktop, browser, CLI tools, and Visual Studio Code |

The default desktop is XFCE and the default browser is LibreWolf. The local
control-plane example selects XFCE explicitly. A browser selected with
`--browser` becomes the default for the setup user; repeat the flag to install
more than one browser.

## Common setups

### Headless agentic coding host

For a Debian VM or server that should run coding agents from SSH or a terminal,
without a desktop or RDP, use the control-plane profile. Add only the language
runtimes your projects need:

```bash
infra-tools setup control_plane 10.0.0.24 agent \
  --agent-tool gh --agent-tool codex --agent-tool claude --agent-tool opencode \
  --node --python --go --agent-config active \
  --git-access read --repo https://github.com/user/project.git
```

This installs the explicitly selected agents, administrator tools, and selected
runtimes. Remove `--agent-config` or `--repo` when those inputs are not needed.
Use `tmux` for long-running agent sessions over SSH.

### Desktop agentic coding workstation with RDP

For a graphical Debian workstation, keep the default desktop profile, select
XFCE for the RDP session, and restrict RDP to the management network:

```bash
infra-tools setup workstation_dev 10.0.0.25 agent \
  --control-plane --desktop xfce --rdp \
  --password "$RDP_PASSWORD" --rdp-source 10.0.0.0/24 \
  --agent-tool gh --agent-tool codex --agent-config active \
  --browser-automation playwright \
  --repo https://github.com/user/project.git
```

This adds the selected agent tools, Playwright browser automation, desktop
browser, Visual Studio Code, administrator tools, and the selected repository.
Repeat `--agent-tool` for any combination
of `gh`, `codex`, `claude`, and `opencode`. Add `--desktop-interface t3code`
for the graphical T3 Code client. The RDP password is
the target Unix
account's password; provide it through a secret-sourced environment variable,
not a literal value in shell history. For a local Debian GNOME machine, use
the [installer handoff](INSTALLATION.md#choose-one-starting-command), which
keeps GNOME for console logins and uses XFCE for RDP.

Agent updates are deliberate rather than automatic; host APT, security,
cleanup, and restart maintenance still runs as described in
[`MAINTENANCE.md`](./MAINTENANCE.md). The default restart policy may force a
restart after seven days of active-session deferrals, so long-running hosts
should use `--no-auto-restart --auto-restart-force-days 0` and manage pending
reboots explicitly.

Minimal developer workstation with RDP:

```bash
infra-tools setup workstation_dev 10.0.0.25 alice \
  --desktop xfce --browser firefox --rdp --password "$RDP_PASSWORD" \
  --rdp-source 10.0.0.0/24
```

PC with office and SMB tools:

```bash
infra-tools setup pc_dev 10.0.0.26 alice \
  --desktop cinnamon --office --browser brave
```

Install several browsers and use a dark theme:

```bash
infra-tools setup workstation_desktop 10.0.0.27 alice \
  --browser librewolf --browser firefox --dark
```

Use `--apt-install PACKAGE` or repeat `--flatpak-install PACKAGE` for
additional packages. Flatpak is enabled with `--flatpak`; the built-in desktop
bundles use it for Discord, LibreOffice, and VS Code when possible.

## Browser choices

This section covers the browser used by a person at the desktop. It does not
configure an MCP server for coding agents; use `--browser-automation
playwright` for that independent capability.

Supported `--browser` values are `brave`, `firefox`, `librewolf`, `helium`,
`browsh`, and `lynx`:

- Brave and LibreWolf use Debian repositories unless `--flatpak` is selected.
- Firefox uses `firefox-esr` through apt, or the Flathub build with Flatpak.
- Helium is downloaded from its upstream GitHub release for amd64 or arm64.
- Browsh installs Firefox as a dependency, resolves the newest stable release
  with a Debian package for the target architecture, and provides a terminal
  browser.
- Lynx installs the Debian terminal browser and does not become a graphical
  default.

Native Discord, Helium, and Browsh packages are staged in private, randomly
named temporary directories and removed after installation. Setup does not
leave uninstalled browser-extension packages in the shared `/tmp` directory.

The first browser in a repeated list is written to the setup user's
`~/.config/mimeapps.list` as the HTTP/HTTPS default. Text-only browsers do not
write a desktop default. XFCE's per-user WebBrowser helper is configured at
the same time, so its launcher does not fall back to the optional
`www-browser` command. A per-user `X-XFCE-Helper` desktop entry is also
created, so XFCE's Preferred Applications dialog and `exo-open --launch
WebBrowser` resolve the selected browser rather than falling back to an
unregistered command. These files are managed defaults: workstation setup
recreates them rather than merging older infra-tools state. This release is
intended for clean workstation builds; rebuild a workstation created by an
older infra-tools release instead of attempting an in-place migration.

On VM and hardware targets, AppArmor is enabled and its distro service reloads
the installed policy without blanket-enforcing package profiles. This preserves
each profile's declared `enforce`, `complain`, or `unconfined` mode. LibreWolf's
own browser sandbox remains responsible for browser confinement. Setup replaces
the package profile with its managed unconfined compatibility profile and
reloads it. This release is intended for clean workstation builds rather than
in-place migration of older infra-tools state.

Debian 13's AppArmor policy also supplies the `unprivileged_userns` transition
used by otherwise-unconfined applications that create a user namespace. Setup
loads and verifies this capability-stripping compatibility profile whenever
the kernel's AppArmor user-namespace restriction is active. This supports
Chromium and Firefox builds downloaded into per-user caches by Playwright and
other browser-automation tools without disabling their sandboxes or granting
an unconfined AppArmor attachment to every executable in a user-writable cache.
If that required profile cannot load, workstation setup stops with a clear
error instead of leaving browser automation silently broken.

## Flatpak and containers

Flatpak requires a desktop-capable host and is unreliable in unprivileged
containers. On a container target, infra_tools warns and falls back to apt for
browsers; other Flatpak bundles may also fall back to apt when Flatpak cannot
be installed. Prefer `--machine vm` when a reproducible Flatpak desktop is
required.

## Desktop and RDP choices

`--desktop` accepts `xfce`, `i3`, `cinnamon`, or `lxqt`. `--rdp` installs and
hardens XRDP; the detailed session, TLS, and dynamic-resolution behavior is in
[`XRDP.md`](./XRDP.md). `--dark` configures XFCE, LXQt, or Cinnamon themes;
i3 receives an informational message because its theme is normally configured
in the user's i3 setup.

When a workstation is provisioned as a hosted Proxmox VM, it receives a
VirtIO-GPU recovery/noVNC console plus a serial socket. XRDP uses its own
xorgxrdp display; setup enables glamor only when the guest exposes a supported,
accessible DRM render node and otherwise uses the software fallback. Changing
the recovery console device alone does not accelerate the remote session. The
complete host-side settings and CPU/migration tradeoffs are in
[`PROXMOX.md`](./PROXMOX.md).

RDP logins use the setup user's Unix password. Remote setups and setups that
create a user require a non-root `--password`; prefer a secret-sourced
environment variable such as `--password "$RDP_PASSWORD"`. For local setup of
an existing desktop account, `--rdp-existing-password` reuses the password
already configured for that account without exposing it in process arguments.
It cannot be combined with `--password`, cannot be used for a remote target,
and does not set or change the account password. Passwords are not written to
saved setup state. State containing this field is sanitized when it is loaded.

Use repeatable `--rdp-source IP_OR_CIDR` flags to restrict UFW ingress to the
trusted LAN, management network, or VPN clients that should connect. Without
one, RDP remains globally rate-limited. XRDP binds all IPv4 interfaces by
default; `--rdp-bind-address IP` narrows the listener to one target-side
address. Clipboard remains enabled for coding workflows, while
drive/device, printer, audio, RemoteApp, and video redirection are disabled.
Use `--no-rdp-clipboard`, `--rdp-drive-redirection`, or `--rdp-audio` to change
the explicitly managed channel policy.

XRDP permits ten sessions and retains disconnected sessions indefinitely by
default. A single-user host can set a smaller `--rdp-max-sessions`; abandoned
sessions can be bounded only by explicitly pairing `--rdp-kill-disconnected`
with a positive `--rdp-disconnected-timeout SECONDS`. `--rdp-idle-timeout`
disconnects an idle client but does not itself end the session. Ending a
disconnected session also ends agents running only inside that graphical
session, so keep durable work in `tmux` or a supervised service before enabling
cleanup.

The `pc_dev` profile includes Remmina with RDP and VNC plugins. Other profiles
can install it through the explicit custom step `install_remmina` when using
`--steps`.

## Verification

After setup, inspect installed applications as the target user:

```bash
command -v firefox librewolf brave-browser code remmina
flatpak list --app
xdg-mime query default x-scheme-handler/https
xdg-settings get default-web-browser
```

For remote sessions, test XRDP separately and use the log checks in
[`XRDP.md`](./XRDP.md). Machine capability differences, including Flatpak
fallbacks and software rendering in containers, are documented in
[`MACHINE_TYPES.md`](./MACHINE_TYPES.md).
