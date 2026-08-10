# Installation and bootstrap

infra_tools runs from a Debian orchestration host and configures Debian target
systems over SSH. The piped installer can also hand off to a local setup,
turning the machine into a control plane for other VMs and containers.

## Requirements

- Python 3.10 or newer on the orchestration host
- Debian on the target
- SSH root access to a remote target, or root privileges for local setup
- Git access to the infra_tools repository

Ubuntu and Linux Mint are recognized as Debian-compatible best-effort hosts;
Debian is the only officially-supported distribution. The setup uses APT
package names shared by current Debian, Ubuntu, and Mint releases.

Before installing packages on Debian, infra_tools checks the installed release
codename and archive keyring, comments out active CD-ROM-only APT entries,
disables stale official Debian suites, and ensures that the current Debian and
security suites use the official `deb.debian.org` and `security.debian.org`
mirrors. It then requires a successful `apt-get update`. This happens before
bootstrap, setup, and recurring APT maintenance, handling the common
minimal/offline installer state where the installation media is still the only
configured source. Existing Debian components such as `non-free-firmware` are
preserved when a managed source file is created. The security profile also
installs the managed APT update timer so package security updates continue
after setup.

Official machine profiles are Debian bare metal, Debian VMs, and unprivileged
Debian LXC on Proxmox. See [Machine types](MACHINE_TYPES.md) for the complete
capability matrix.

## Install for the current user

The installer clones a local Git worktree, installs prerequisites, and creates
a user-scoped launcher. Privileged actions request `sudo` only when needed:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
```

The equivalent `wget` command is:

```bash
wget -qO- https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
```

Review [`install.sh`](../install.sh) before running a network-piped installer,
especially on a privileged machine.

## Install a system launcher

For a system-wide source tree and `/usr/local/bin/infra_tools` launcher:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER"
```

The installed repository is kept locally so its channel can be changed without
reinstalling the launcher. The default channel is `dev`, which tracks `main`
while this managed installation workflow is being introduced. Select the
latest tagged release explicitly when desired:

```bash
infra_tools channel stable
```

The source directory is printed by the installer. It defaults to
`~/.local/share/infra_tools` for a user install and `/opt/infra_tools` for a
root install. Use `infra_tools channel` to inspect the active channel and
commit.

The installer can hand off immediately to a normal setup command:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sh -s -- \
  --setup server_dev localhost "$USER" \
  --machine hardware \
  --agent-suite terminal
```

`server_dev` is the recommended CLI-only agent profile because it includes the
standard firewall and CLI tools. `server_lite` intentionally omits those parts
of the profile.

## Local control-plane setup

Use `--local-setup` when the setup target is the same machine running the
installer. It supplies `localhost` and the selected `--user` automatically,
then runs the setup after the managed source and launcher are installed. The
managed Git worktree is preserved, so later `infra_tools channel` and
`infra_tools upgrade` commands continue to work.

The `control_plane` profile is intended for a minimal Debian server. It adds
common administrator and Linux tools such as SSH, rsync, tmux, Neovim, jq,
network diagnostics, ripgrep, fd, fzf, ShellCheck, and package/file utilities:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup control_plane --agent-suite terminal
```

Add `--copy-config`, `--copy-keys`, or repeat `--repo GIT_URL` when the control
plane should receive selected agent configuration, credentials, or local agent
repositories. These options are deliberately opt-in.

For a standard Debian desktop, add the control-plane tools to the desktop
developer profile. This keeps the existing graphical desktop and adds the same
administration bundle plus the desktop agent tools:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup workstation_dev --control-plane \
  --agent-suite desktop --desktop xfce
```

Use `--agent-suite terminal` on a headless host, `desktop` when a graphical
agent is wanted, or `full` when Node.js, Python tooling, and Go are also needed.
The example selects XFCE explicitly; use `--desktop i3`, `--desktop cinnamon`,
or `--desktop lxqt` when another supported session is preferred. Add `--rdp`
and a trusted `--rdp-source` only when remote graphical login is required; RDP
also requires a non-root setup user's password.

The equivalent explicit form remains available when more control is needed:

```bash
sudo infra_tools setup control_plane localhost "$USER" --agent-suite terminal
```

Direct Python entry scripts remain a development and recovery fallback; the
installed launcher and installer handoff are the supported workflow.

For a remote Proxmox host, pass the target setup after `--setup`:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --setup server_proxmox 10.0.0.10 root \
  --key "$HOME/.ssh/proxmox_ed25519" \
  --name pve1
```

The installer preserves the previous source tree as a timestamped backup when
reinstalling. A failed bootstrap restores the previous source. Existing local
changes in a managed worktree must be committed or stashed before reinstalling.

## Channels and upgrades

Channels are resolved from the local repository's `origin` remote:

| Channel | Meaning |
| --- | --- |
| `stable` | Highest `vMAJOR.MINOR.PATCH` release tag |
| `dev` | `main` branch; equivalent to `branch-main` |
| `v<version>` | Exact version tag, such as `v1.2.3` |
| `branch-<branch>` | Any existing branch, including `branch-feature/example` |
| `commit-<hash>` | An exact Git commit hash |

Switch channels with:

```bash
infra_tools channel dev
infra_tools channel v1.2.3
infra_tools channel branch-feature/example
infra_tools channel commit-0123456789abcdef
```

Run the upgrade command without a host to fetch and install the newest commit
available on the selected channel:

```bash
infra_tools upgrade
```

`infra_tools upgrade` refuses to overwrite local worktree changes. The existing
remote-host form remains available when hosts are supplied, for example
`infra_tools upgrade web1 web2`.

## First setup commands

```bash
# Web server with a deployment
infra_tools setup server_web example.com admin \
  --ruby --node --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git

# Developer workstation
infra_tools setup workstation_desktop 192.168.1.100 admin \
  --desktop i3 --browser firefox

# Patch an existing saved host
infra_tools patch example.com admin --ssl
```

Use the [Command-line reference](COMMAND_LINE.md) for all setup and patch
flags. See [Samba shares](SAMBA_SHARES.md) for storage-specific setup.

## Workspace and credentials

Workspace state defaults to `~/.config/infra_tools`. Set an isolated workspace
for a project or test environment:

```bash
infra_tools --workspace /srv/infra-tools-workspace list
```

Workspace credentials are stored separately with restrictive permissions. Enter
passwords interactively whenever possible:

```bash
infra_tools credentials set alice
infra_tools credentials list
infra_tools credentials remove alice
```

Passwords are excluded from saved setup state and reconstructed commands.

## Shell completion

Install `argcomplete` and register completion for the unified launcher:

```bash
uv tool install --upgrade argcomplete
infra_tools completions
```

For manual Bash, Zsh, Fish, or system-wide installation, see
[Shell completion](SHELL_COMPLETION.md).

## Updating the source

The installed launcher manages source updates:

```bash
infra_tools upgrade
```

For development or recovery, the Python entry script still works directly from
a checkout (for example, `python3 infra_tools.py setup ...`), but that path does
not replace the managed installed launcher.

Saved configurations can be inspected with `infra_tools info`; use `patch` or
feature-specific fast paths for targeted changes.
