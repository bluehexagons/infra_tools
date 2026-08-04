# Workstations and desktop applications

The workstation system types build a Debian desktop from the same
machine-aware setup pipeline used for servers. Choose a profile first, then
override the desktop, browser, or application choices with flags.

## Profiles

| Profile | Adds by default |
| --- | --- |
| `workstation_desktop` | Desktop, CLI tools, browser, LibreOffice-style desktop apps, and Discord |
| `pc_dev` | Desktop, browser, office apps, SMB client packages, Remmina, and Discord |
| `workstation_dev` | Desktop, browser, CLI tools, and Visual Studio Code |

The default desktop is XFCE and the default browser is LibreWolf. A browser
selected with `--browser` becomes the default for the setup user; repeat the
flag to install more than one browser.

## Common setups

Minimal developer workstation with RDP:

```bash
infra_tools setup workstation_dev 10.0.0.25 alice \
  --desktop xfce --browser firefox --rdp
```

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
