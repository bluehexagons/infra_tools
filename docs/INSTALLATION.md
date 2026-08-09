# Installation and bootstrap

infra_tools runs from a Debian orchestration host and configures Debian target
systems over SSH. It can also configure the local host with `localhost` when
run as root.

## Requirements

- Python 3.10 or newer on the orchestration host
- Debian on the target
- SSH root access to a remote target, or root privileges for local setup
- A current checkout when running from source

Official machine profiles are Debian bare metal, Debian VMs, and unprivileged
Debian LXC on Proxmox. See [Machine types](MACHINE_TYPES.md) for the complete
capability matrix.

## Install for the current user

The installer downloads the source, installs prerequisites, and creates a
user-scoped launcher. Privileged actions request `sudo` only when needed:

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

From an existing checkout, the same bootstrap flow is:

```bash
sudo python3 infra_tools.py self-setup --user "$USER"
```

`self-setup` is an alias for `bootstrap`. It installs the local launcher and
completion, and can install the system packages needed by the orchestration
host. Afterward, use `infra_tools <command> ...` from any directory.

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

For a remote Proxmox host, pass the target setup after `--setup`:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --setup server_proxmox 10.0.0.10 root \
  --key "$HOME/.ssh/proxmox_ed25519" \
  --name pve1
```

The installer preserves the previous source tree as a timestamped backup when
updating. A failed bootstrap restores the previous source.

## First setup commands

```bash
# Web server with a deployment
python3 infra_tools.py setup server_web example.com admin \
  --ruby --node --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git

# Developer workstation
python3 infra_tools.py setup workstation_desktop 192.168.1.100 admin \
  --desktop i3 --browser firefox

# Patch an existing saved host
python3 infra_tools.py patch example.com admin --ssl
```

Use the [Command-line reference](COMMAND_LINE.md) for all setup and patch
flags. See [Samba shares](SAMBA_SHARES.md) for storage-specific setup.

## Workspace and credentials

Workspace state defaults to `~/.config/infra_tools`. Set an isolated workspace
for a project or test environment:

```bash
python3 infra_tools.py --workspace /srv/infra-tools-workspace list
```

Workspace credentials are stored separately with restrictive permissions. Enter
passwords interactively whenever possible:

```bash
python3 infra_tools.py credentials set alice
python3 infra_tools.py credentials list
python3 infra_tools.py credentials remove alice
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

From a checkout, update before setup work:

```bash
git pull --ff-only
sudo python3 infra_tools.py self-setup --user "$USER"
```

Saved configurations can be inspected with `infra_tools info`; use `patch` or
feature-specific fast paths for targeted changes.
