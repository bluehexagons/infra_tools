# Install infra_tools

Use the installer on the machine that will manage your hosts. It keeps a local
Git worktree, installs the managed `infra_tools` launcher, and can configure
the same machine immediately.

Debian is the only officially supported distribution. Ubuntu and Linux Mint are
recognized as best-effort Debian-compatible hosts.

## Choose an installation path

Run these commands in a terminal as the local account that should own the
installation. Replace `$USER` only when installing for a different existing
account.

### Install the launcher only

Use this when you want to choose the first setup later:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
```

The installer uses `sudo` for packages when needed. To install the source in
`/opt/infra_tools` and expose a system launcher instead, use:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER"
```

### Set up a minimal Debian control plane

This installs common administrator and Linux tools, the terminal agent suite,
and configures the local machine to manage other VMs and containers:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup control_plane --agent-suite terminal
```

### Set up a Debian GNOME desktop control plane

Use this for a standard Debian desktop that already has GNOME. It leaves GNOME
available for local logins, adds XFCE for RDP sessions, enables RDP, and
installs the desktop agent suite:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup workstation_dev --control-plane \
  --agent-suite desktop --desktop xfce \
  --rdp --rdp-existing-password
```

This expects `$USER` to be an existing non-root account with an unlocked
password. `--rdp-existing-password` reuses that password without putting it in
the command line; it does not create or reset an account password. Add a
trusted network restriction when you know the management range, for example:

```text
--rdp-source 192.168.1.0/24
```

Without `--rdp-source`, RDP is available on all local interfaces with the
configured rate-limited firewall rule. See [XRDP](XRDP.md) for connection and
firewall details.

Use `--agent-suite terminal` on a headless host, `desktop` for graphical agent
tools, or `full` when Node.js, Python, and Go tooling are also wanted. Append
`--copy-config`, `--copy-keys`, or `--repo GIT_URL` when the control plane
should receive selected agent settings, credentials, or repositories; these
options are intentionally opt-in.

## Verify the installation

Start a new login shell if necessary, then run:

```bash
command -v infra_tools
infra_tools channel
infra_tools --help
```

If the command is not found in a user installation, add its directory for the
current shell and start a new login shell later:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Before applying a setup for the first time, validate its profile with a dry
run. Local setup preflight still needs root, so use `sudo`; the dry run
validates arguments and prints the steps without changing the target:

```bash
sudo "$(command -v infra_tools)" setup workstation_dev localhost "$USER" \
  --control-plane --agent-suite desktop --desktop xfce --rdp \
  --rdp-existing-password --dry-run
```

For the all-in-one commands above, the installer runs this local setup after
installing the launcher, so a separate setup command is not required.

## Install and configure a remote host

Install the launcher on the control plane first, then run setup through the
installed command. The remote account must be reachable over SSH and have the
privileges required by the selected profile:

```bash
infra_tools setup server_web example.com admin \
  --ruby --node --ssl --ssl-email admin@example.com
```

For agentic coding targets, use the [headless terminal example](WORKSTATIONS.md#headless-agentic-coding-host)
when no desktop or RDP is wanted, or the [desktop/RDP example](WORKSTATIONS.md#desktop-agentic-coding-workstation-with-rdp)
for graphical work. For a Proxmox node, start with [Proxmox workflows](PROXMOX.md).

## Channels and upgrades

The installer downloads the repository into a managed local worktree. The
launcher stays installed while the worktree's channel changes:

| Channel | Selects |
| --- | --- |
| `stable` | Latest `vMAJOR.MINOR.PATCH` release tag |
| `dev` | `main` branch |
| `v<version>` | One release tag, such as `v1.2.3` |
| `branch-<branch>` | Any existing branch |
| `commit-<hash>` | One exact commit |

Inspect or change the selected channel:

```bash
infra_tools channel
infra_tools channel stable
infra_tools channel dev
```

Update the local installation to the newest commit on its selected channel:

```bash
infra_tools upgrade
```

The default installer channel is `dev`, which tracks `main`. Use `stable` when
you want the latest versioned release. `upgrade` refuses to overwrite local
worktree changes; commit or stash changes before reinstalling or upgrading.

## Debian package sources

The installer and setup need network access to APT. On Debian, they check the
release codename and archive keyring, disable active CD-ROM-only entries, and
ensure the current release uses the official mirrors:

- `https://deb.debian.org/debian` for the base and updates suites;
- `https://security.debian.org/debian-security` for security updates.

If a minimal or offline Debian installation has only installation media
configured, infra_tools creates a managed source file and runs `apt-get
update` before installing packages. Existing `non-free-firmware` components
are preserved. Existing source files are backed up, and an unmanaged
`infra_tools-debian.sources` file is not overwritten.

If this step fails, fix network, DNS, proxy, or mirror access and rerun the
same installer command. Do not work around a failed package-list update by
leaving a CD-ROM as the only source.

## Optional local tools

The installer already bootstraps the launcher and shell completion. For a
manual completion refresh or another shell:

```bash
infra_tools completions --shell bash
infra_tools completions --shell zsh
```

See [Shell completion](SHELL_COMPLETION.md) for system-wide and Fish setup.

## Workspace and credentials

Saved host state defaults to `~/.config/infra_tools`. Use another workspace
when separating projects or test environments:

```bash
infra_tools --workspace /srv/infra-tools-workspace list
```

Store remote credentials separately and prefer interactive entry:

```bash
infra_tools credentials set admin
infra_tools credentials list
infra_tools credentials remove admin
```

Passwords are excluded from saved setup state and reconstructed commands.

## Related guides

- [Command-line reference](COMMAND_LINE.md) — all setup flags and system types
- [Workstations](WORKSTATIONS.md) — desktop profiles, browsers, and agents
- [XRDP](XRDP.md) — RDP sessions and firewall behavior
- [Machine types](MACHINE_TYPES.md) — Debian VMs, bare metal, and containers

Review [`install.sh`](../install.sh) before running a network-piped installer
on a privileged machine.
