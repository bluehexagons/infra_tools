# Local system maintenance

Use the `local` command for focused changes to the Debian machine where
`infra-tools` is installed. These commands reuse the same package, desktop,
browser, hostname, and network steps used by full setup, but do not rebuild
the whole workstation or control-plane profile.

Mutating local commands require root, so run them with `sudo`. Use
`--dry-run` before a change when the command supports it:

```bash
sudo infra-tools local --help
sudo infra-tools local install --dry-run btop ripgrep
```

## Packages and system updates

Refresh Debian package metadata, upgrade installed packages, and remove
packages APT no longer needs:

```bash
sudo infra-tools local update
```

Install one or more Debian packages without running the rest of setup:

```bash
sudo infra-tools local install neovim tmux jq
```

Package names are validated before APT runs. The command uses the same
noninteractive APT behavior as setup. If APT sources need repair first, use
`local update`.

For larger changes that also need a language runtime, security policy, or
maintenance timer, use the normal local setup flags instead:

```bash
sudo infra-tools setup workstation_dev localhost "$USER" \
  --node --python --go --dry-run
```

## Desktop environments

Install an additional supported desktop environment directly:

```bash
sudo infra-tools local desktop xfce
sudo infra-tools local desktop cinnamon --dark
```

Supported environments are `xfce`, `i3`, `cinnamon`, and `lxqt`. This command
installs the selected environment alongside any existing desktop; it does not
remove GNOME or another environment. At the next graphical login, select the
session from the display manager. `--dark` applies the existing supported
theme configuration where available.

For a complete RDP setup—including XRDP installation, TLS hardening, session
configuration, and firewall rules—use a workstation setup with `--rdp` rather
than the focused desktop command:

```bash
sudo infra-tools setup workstation_dev localhost "$USER" \
  --desktop xfce --rdp --rdp-existing-password
```

## Browsers and desktop applications

Install a supported browser without repeating desktop setup:

```bash
sudo infra-tools local browser firefox
sudo infra-tools local browser librewolf --flatpak --no-default
```

The default behavior configures the browser for the local desktop user. Use
`--no-default` when installing a secondary browser. Supported browsers are
`brave`, `firefox`, `librewolf`, `helium`, `browsh`, and `lynx`.

For bundled applications such as LibreOffice, VS Code, Discord, or Remmina,
use the workstation profile's existing flags and inspect the plan first:

```bash
sudo infra-tools setup workstation_dev localhost "$USER" \
  --office --browser firefox --dry-run
```

## Hostname, IP address, and DNS

Set the persistent hostname without rerunning the full setup:

```bash
sudo infra-tools local hostname workstation-01
```

View current interface addresses:

```bash
infra-tools local ip
```

Stage a static IPv4 address, gateway, and DNS servers:

```bash
sudo infra-tools local ip 192.168.1.50/24 \
  --gateway 192.168.1.1 \
  --dns 1.1.1.1 --dns 1.0.0.1 \
  --interface enp1s0
```

Use `local network` for a dual-stack configuration:

```bash
sudo infra-tools local network \
  --ip 192.168.1.50/24 --gateway 192.168.1.1 \
  --ipv6 2001:db8:1::50/64 --gateway6 2001:db8:1::1 \
  --dns 1.1.1.1 --dns 2606:4700:4700::1111 \
  --interface enp1s0
```

The network commands support NetworkManager, systemd-networkd, and ifupdown.
They write persistent configuration and deliberately do not restart the
active interface, so an SSH session is not cut off. The command reports the
backend it selected. Reboot, or deliberately restart the interface after
reviewing the generated configuration, to activate the change. On ifupdown
systems, the previous configuration receives an `.infra-tools.bak` backup.

Do not apply a static address over an SSH-only connection unless you have an
out-of-band console or another recovery path. Use `--dry-run` to validate the
requested values and see the intended interface before writing anything.

## Other local maintenance commands

The focused commands complement, rather than replace, the existing local
tools:

```bash
# Install or refresh the infra-tools launcher and its base dependencies.
sudo infra-tools bootstrap

# Install Python aliases, uv, and shell completion support.
infra-tools python-tools

# Refresh shell completion files.
infra-tools completions --shell bash

# Inspect and deliberately update user-installed coding agents.
infra-tools agent doctor
infra-tools agent update --dry-run

# Inspect or change the infra-tools source channel, then update it.
infra-tools channel
infra-tools upgrade
```

Use `infra-tools setup ... localhost ...` when several changes should be
coordinated, when a profile's security and maintenance steps are needed, or
when the operation is part of a saved configuration. Use the focused `local`
commands for small, independent maintenance tasks.
