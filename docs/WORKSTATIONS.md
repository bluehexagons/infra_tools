# Workstations and desktop applications

The workstation system types build a Debian desktop from the same
machine-aware setup pipeline used for servers. Choose a profile first, then
override the desktop, browser, or application choices with flags.

To use a Debian desktop as the local control plane, combine the workstation
profile with `--control-plane`:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup workstation_dev --control-plane --agent-suite desktop
```

This keeps the graphical workstation setup while adding the SSH, rsync,
diagnostic, terminal, and package-management tools used to administer other
VMs and containers. Use `--agent-suite terminal` if no graphical agents are
needed, or `full` for the additional language runtimes.

## Profiles

| Profile | Adds by default |
| --- | --- |
| `workstation_desktop` | Desktop, CLI tools, browser, and Discord |
| `pc_dev` | Desktop, browser, LibreOffice, SMB client packages, Remmina, and Discord |
| `workstation_dev` | Desktop, browser, CLI tools, and Visual Studio Code |

The default desktop is XFCE and the default browser is LibreWolf. A browser
selected with `--browser` becomes the default for the setup user; repeat the
flag to install more than one browser.

## Common setups

Minimal developer workstation with RDP:

```bash
infra_tools setup workstation_dev 10.0.0.25 alice \
  --desktop xfce --browser firefox --rdp --password "$RDP_PASSWORD" \
  --rdp-source 10.0.0.0/24
```

RDP-capable agentic coding workstation:

```bash
infra_tools setup workstation_dev 10.0.0.25 agent \
  --desktop xfce --rdp --password "$RDP_PASSWORD" \
  --rdp-source 10.0.0.0/24 \
  --agent-suite terminal --copy-config \
  --repo https://github.com/user/project.git
```

This adds the terminal agent suite to the browser and Visual Studio Code
profile. Agent updates are deliberate rather than automatic; host APT,
security, cleanup, and restart maintenance still runs as described in
[`MAINTENANCE.md`](./MAINTENANCE.md). The default restart policy may force a
restart after seven days of active-session deferrals, so long-running hosts
should use `--no-auto-restart --auto-restart-force-days 0` and manage pending
reboots explicitly.

PC with office and SMB tools:

```bash
infra_tools setup pc_dev 10.0.0.26 alice \
  --desktop cinnamon --office --browser brave
```

Install several browsers and use a dark theme:

```bash
infra_tools setup workstation_desktop 10.0.0.27 alice \
  --browser librewolf --browser firefox --dark
```

Use `--apt-install PACKAGE` or repeat `--flatpak-install PACKAGE` for
additional packages. Flatpak is enabled with `--flatpak`; the built-in desktop
bundles use it for Discord, LibreOffice, and VS Code when possible.

## Browser choices

Supported `--browser` values are `brave`, `firefox`, `librewolf`, `helium`,
`browsh`, and `lynx`:

- Brave and LibreWolf use Debian repositories unless `--flatpak` is selected.
- Firefox uses `firefox-esr` through apt, or the Flathub build with Flatpak;
  setup also downloads the uBlock Origin extension package to `/tmp`.
- Helium is downloaded from its upstream GitHub release for amd64 or arm64.
- Browsh installs Firefox as a dependency and provides a terminal browser.
- Lynx installs the Debian terminal browser and does not become a graphical
  default.

The first browser in a repeated list is written to the setup user's
`~/.config/mimeapps.list` as the HTTP/HTTPS default. Text-only browsers do not
write a desktop default.

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
VirtIO-GPU recovery/noVNC console plus a serial socket. XRDP still uses its own
software-rendered xorgxrdp display, so changing the Proxmox emulated graphics
card does not accelerate the remote session. The complete host-side settings
and CPU/migration tradeoffs are in [`PROXMOX.md`](./PROXMOX.md).

RDP logins use the setup user's Unix password, so `--rdp` requires a non-root
`--password`. Prefer a secret-sourced environment variable such as
`--password "$RDP_PASSWORD"`; passwords are not written to saved setup state.
Legacy state containing this field is sanitized when it is loaded.

Use repeatable `--rdp-source IP_OR_CIDR` flags to restrict UFW ingress to the
trusted LAN, management network, or VPN clients that should connect. Without
one, RDP remains globally rate-limited for backward compatibility. XRDP binds
all IPv4 interfaces by default; `--rdp-bind-address IP` narrows the listener to
one target-side address. Clipboard remains enabled for coding workflows, while
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
```

For remote sessions, test XRDP separately and use the log checks in
[`XRDP.md`](./XRDP.md). Machine capability differences, including Flatpak
fallbacks and software rendering in containers, are documented in
[`MACHINE_TYPES.md`](./MACHINE_TYPES.md).

The remaining RDP exposure, certificate, session-lifecycle, maintenance, and
live-test work is tracked in the
[RDP desktop agent audit](plans/DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md).
