# Install infra-tools

Use the installer on the machine that will manage your hosts. It keeps a local
Git worktree, installs the managed `infra-tools` launcher, and can configure
the same machine immediately.

Debian is the only officially supported distribution. Ubuntu and Linux Mint are
recognized as best-effort Debian-compatible hosts.

## Unsupported orchestration hosts

The installer can also install the remote-management launcher on another Linux
distribution, such as CachyOS, but this remains outside the support guarantee.
It asks for an explicit `[y/N]` confirmation, does not attempt to install APT
packages, and requires these controller commands to already be available:

- `python3`
- `git`
- `ssh`
- `rsync`
- `curl` or `wget`

Install the equivalent packages with the host distribution's package manager
before rerunning the installer. For example, on CachyOS, the equivalent setup
is approximately:

```bash
sudo pacman -Syu --needed python git openssh rsync curl ca-certificates tar
```

The installer skips local system-package bootstrap on unsupported hosts. Do not
use `--local-setup` or `--qemu-guest-agent` there; install the launcher and use
remote-management commands such as `setup`, `patch`, `ssh`, `push`, and `pull`.
Remote setup profiles and target-side package operations remain Debian-oriented.

The installer needs either `wget` or `curl`. The examples below use wget,
which is commonly present on minimal Debian systems. If only `curl` is
installed, replace the download command with
`curl --fail --location --connect-timeout 15 --max-time 120 -o "$HOME/.infra_tools-install.sh" URL`.
If neither command is available, install one first with:

```bash
sudo apt-get update && sudo apt-get install -y wget ca-certificates
```

The fetch command leaves DNS and connection diagnostics visible and limits
retries, so a VM with no network path fails clearly instead of appearing idle.
Every example downloads to a user-owned file before invoking the installer.
Run each command in order and confirm the download succeeds before running the
installer command; remove the file afterward.

## Choose an installation path

Run these commands in a terminal as the local account that should own the
installation. Replace `$USER` only when installing for a different existing
account.

### Install the launcher only

Use this when you want to choose the first setup later:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sh "$HOME/.infra_tools-install.sh"
rm -f "$HOME/.infra_tools-install.sh"
```

The installer uses `sudo` for packages when needed. To install the source in
`/opt/infra_tools` and expose a system launcher instead, use:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER"
rm -f "$HOME/.infra_tools-install.sh"
```

### Set up a minimal Debian control plane

This installs common administrator and Linux tools and configures the local
machine to manage other VMs and containers. Select agent tools explicitly:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --local-setup control_plane \
  --agent-tool gh --agent-tool codex --agent-tool claude --agent-tool opencode
rm -f "$HOME/.infra_tools-install.sh"
```

If the orchestration machine is itself a Proxmox VM, add
`--qemu-guest-agent` before `--local-setup`. The installer then installs the
guest-agent package and starts and enables its systemd service during
self-setup:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --qemu-guest-agent \
  --local-setup control_plane --agent-tool gh --agent-tool codex
rm -f "$HOME/.infra_tools-install.sh"
```

For an already installed orchestration host, run the equivalent command:

```bash
sudo infra-tools self-setup --qemu-guest-agent
```

Use this on a VM only; the QEMU guest agent is not applicable to an LXC
container. `--qemu-guest-agent` requires root and system-package installation.

### Set up a Debian GNOME desktop control plane

Use this for a standard Debian desktop that already has GNOME. It leaves GNOME
available for local logins, adds XFCE for RDP sessions, enables RDP, and
installs the selected agent tools (GitHub CLI and Codex CLI in this example):

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --local-setup agent_workstation \
  --control-plane --desktop xfce --rdp --rdp-existing-password
rm -f "$HOME/.infra_tools-install.sh"
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

The `agent_vm`, `agent_workstation`, and `agent_code_vm` profiles default to
GitHub CLI and Codex. `--agent-tool` values add to those defaults and accept
comma-separated lists; use `--no-agent-tool` to remove a default. The
`agent_code_vm` profile additionally defaults to Geany, T3 Code, Playwright,
RDP, T3 pairing, read-write Git, and active auth sources. It does not assume a
management network; add `--lan-access`, `--access-source`, or service-specific
source flags explicitly. Its T3 Code service requires explicit `--node` and
`--go`; add Python only when the project needs it. Use
`--agent-config active`, `--git-auth active`, or the specified-file credential
options when the control plane should transfer selected settings or
credentials. Active GitHub auth can use the controller's `gh auth token`
command when the token is stored in the controller's keyring; file-backed
Codex, Claude Code, and OpenCode credentials must be supplied as files. Use
`--repo GIT_URL` for target-side HTTPS clones; public repositories on any
reachable Git host are supported.
The [credentials guide](CREDENTIALS.md) explains the difference between
workspace passwords, GitHub auth, agent auth, and non-secret agent config.

Setup reruns reuse completed package and tool work. Use `--refresh-packages`
when you deliberately want a new APT update/upgrade and versioned runtime
check; the flag is one-shot and is not retained in the saved setup command.

## Verify the installation

Start a new login shell if necessary, then run:

```bash
command -v infra-tools
infra-tools channel
infra-tools --help
```

The installed command is `infra-tools`; the legacy `infra_tools` command is no
longer supported.
Rerunning bootstrap removes a regular-file or symlink launcher named
`infra_tools` from the configured system or user launcher directory before
installing the new command. Self-setup also removes generated shell completion
registrations and files for `infra_tools` and `infra_tools.py` while installing
the `infra-tools` completion for the configured shell.

If the command is not found in a user installation, add its directory for the
current shell and start a new login shell later:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Before applying a setup for the first time, validate its profile with a dry
run. Local setup preflight still needs root, so use `sudo`; the dry run
validates arguments and prints the steps without changing the target:

```bash
sudo "$(command -v infra-tools)" setup agent_workstation localhost "$USER" \
  --control-plane --desktop xfce --rdp \
  --rdp-existing-password --dry-run
```

For the all-in-one commands above, the installer runs this local setup after
installing the launcher, so a separate setup command is not required.
SSH hardening is applied when `openssh-server` is present; an outbound-only
control plane without `sshd` reports a skip instead of failing the setup.

Tagged GitHub releases also attach a Python wheel. Release CI installs that
wheel into an isolated environment and smoke-tests both packaged entry points
before publication. The source installer remains the recommended operator path
because it provides channel selection and worktree-aware upgrades; the wheel is
primarily a verified release artifact and an option for externally managed
Python environments.

## Install and configure a remote host

Install the launcher on the control plane first, then run setup through the
installed command. The remote account must be reachable over SSH and have the
privileges required by the selected profile:

```bash
infra-tools setup server_web example.com admin \
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
infra-tools channel
infra-tools channel stable
infra-tools channel dev
```

Update the local installation to the newest commit on its selected channel:

```bash
infra-tools upgrade
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
configured, infra-tools creates a managed source file and runs `apt-get
update` before installing packages. Existing `non-free-firmware` components
are preserved. Existing source files are backed up, and an unmanaged
`infra_tools-debian.sources` file is not overwritten. Existing current Debian
base and security entries are reused; the managed file is limited to any
missing suite, and a redundant managed file from an older installer run is
removed.

The installer and local setup print APT progress directly. The first run may
pause briefly while another package operation releases the APT lock (the
wait is bounded), but it should continue to show package-list or package
installation output. Keep the terminal open until the installer reports its
completion message. If a previously started installer was interrupted, rerun
the same command after checking that no other `apt` or `dpkg` process is still
active.

If this step fails, fix network, DNS, proxy, or mirror access and rerun the
same installer command. Do not work around a failed package-list update by
leaving a CD-ROM as the only source.

## Optional local tools

The installer already bootstraps the launcher and shell completion. For a
manual completion refresh or another shell:

```bash
infra-tools completions --shell bash
infra-tools completions --shell zsh
```

See [Shell completion](SHELL_COMPLETION.md) for system-wide and Fish setup.

## Workspace and credentials

Saved host state defaults to `~/.config/infra_tools`. Use another workspace
when separating projects or test environments:

```bash
infra-tools --workspace /srv/infra-tools-workspace list
```

The `credentials` commands manage the workspace password store used by
features such as Samba/SMB; they do not configure GitHub, Codex, Claude Code,
or OpenCode:

```bash
infra-tools credentials set admin
infra-tools credentials list
infra-tools credentials remove admin
```

Passwords are excluded from saved setup state and reconstructed commands.

For agent VM authentication, Git policy, active/file sources, per-VM
credential isolation, and remote rotation, see [Credentials and agent
configuration](CREDENTIALS.md).

## Related guides

- [Command-line reference](COMMAND_LINE.md) — all setup flags and system types
- [Credentials and agent configuration](CREDENTIALS.md) — workspace passwords,
  Git access, agent auth, configuration, sharing, and rotation
- [Workstations](WORKSTATIONS.md) — desktop profiles, browsers, and agents
- [XRDP](XRDP.md) — RDP sessions and firewall behavior
- [Machine types](MACHINE_TYPES.md) — Debian VMs, bare metal, and containers

Review [`install.sh`](../install.sh) before running a network-piped installer
on a privileged machine.
