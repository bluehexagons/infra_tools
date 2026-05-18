# Command-Line Reference

Complete reference for the unified infra_tools CLI.

> **Sysadmin shortcuts** (`mount`, `health`, `ssh`, `push`, `pull`, `df`, `fan`,
> `svc`, `logs`, `upgrade`, `reachable`, `key`) have their own page:
> [SYSADMIN.md](./SYSADMIN.md).
>
> **Network inventory and Proxmox firewall planning** (`network ...`) have
> their own page: [NETWORKING.md](./NETWORKING.md).

## Unified Entry Point

The `infra_tools.py` script provides a unified interface for all operations:

```bash
# Setup a new system
infra_tools.py setup <system_type> <host> [username] [options]

# Patch/update an existing system  
infra_tools.py patch <host> [username] [options]

# Recall a saved or reconstructed setup command from a remote host
infra_tools.py recall <host> [username] [options]

# Reconstruct this host's setup summary
infra_tools.py reconstruct [--compact]

# Inspect, manage, or redeploy saved configurations
infra_tools.py list [pattern] [--json]
infra_tools.py info [pattern] [--compact]
infra_tools.py cmd [pattern]
infra_tools.py rm <pattern>
infra_tools.py deploy <pattern> [--yes]

# Manage workspace credentials
infra_tools.py credentials set <username> <password>
infra_tools.py credentials list
infra_tools.py credentials remove <username>

# Install shell completion or local Python tooling
infra_tools.py completions [options]
infra_tools.py python-tools [options]

# Bootstrap the local orchestration host (alias: self-setup)
infra_tools.py bootstrap [options]
infra_tools.py self-setup [options]

# Drop into the interactive infra_tools REPL
infra_tools.py shell

# Workspace-backed network inventory and read-only Proxmox firewall planning
infra_tools.py network list
infra_tools.py network init <profile> [--management CIDR] [--control-plane CIDR] [--guest-network CIDR]
infra_tools.py network add-host <profile> <name> <address> [--provider NAME] [--role ROLE]
infra_tools.py network import-proxmox <profile> [--host NAME] [--tag TAG]
infra_tools.py network import-proxmox-guests <profile> [--host NAME] [--tag TAG]
infra_tools.py network plan-proxmox <profile> [--proxmox] [--json]

# Sysadmin shortcuts (see SYSADMIN.md for full reference)
infra_tools.py mount <host>:<path> <local>
infra_tools.py umount <local|host>
infra_tools.py health <host>
infra_tools.py ssh <host> [-- cmd]
infra_tools.py push <local> <host>:<path>
infra_tools.py pull <host>:<path> [local]
infra_tools.py key push <host>
infra_tools.py df <host> [<host2> ...]
infra_tools.py fan <host> [<host2> ...] -- <cmd>
infra_tools.py svc <host> <unit> [action]
infra_tools.py logs <host> <unit> [-f] [-n N]
infra_tools.py upgrade <host> [<host2> ...] [--check]
infra_tools.py reachable [hosts|--pattern GLOB]
```

### System Types for `setup` command

| Type | Description |
|------|-------------|
| `workstation_desktop` | Desktop workstation with GUI |
| `pc_dev` | PC development environment |
| `workstation_dev` | Developer workstation |
| `server_dev` | Development server |
| `server_web` | Web server |
| `server_lite` | Lightweight server |
| `server_proxmox` | Proxmox host server |

### Examples

```bash
# Setup a web server
infra_tools.py setup server_web 192.168.1.100 admin --ruby --ssl

# Setup a desktop workstation
infra_tools.py setup workstation_desktop 192.168.1.50 --desktop i3 --browser firefox

# Patch an existing server
infra_tools.py patch web.com --deploy api.web.com https://github.com/user/api.git

# Provision a hosted Proxmox VM, then configure it as a web server
infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted pve1 \
  --memory 4G \
  --storage root 32G \
  --cores 2 \
  --base debian \
  --name web-01-vm \
  --ruby --node --ssl
```

---

## Basic Flags

| Flag | Description |
|------|-------------|
| `host` | IP address or hostname (positional argument) |
| `username` | Username (positional, optional, defaults to current user) |
| `-k, --key PATH` | SSH private key path |
| `-p, --password PASS` | User password |
| `-t, --timezone TZ` | Timezone (defaults to UTC) |
| `--workspace PATH` | Workspace root for config, credentials, known_hosts, and history |
| `--machine TYPE` | Machine type override. Defaults are system-specific: VM for workstation_desktop/workstation_dev/pc_dev/server_web and build-server flows; otherwise `unprivileged` (LXC) |
| `--name NAME` | Friendly name for this configuration |
| `--tags TAG1,TAG2` | Comma-separated tags for this configuration |
| `--dry-run` | Simulate execution without making changes |
| `--no-restart` | Disable automatic restarts after updates |

## Desktop/Workstation Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable/disable RDP/XRDP (default: disabled) |
| `--audio` / `--no-audio` | Enable/disable audio setup |
| `--desktop [xfce\|i3\|cinnamon\|lxqt]` | Desktop environment (default: xfce) |
| `--browser NAME` | Browser to install (can be used multiple times) |
| `--flatpak` | Install desktop apps via Flatpak |
| `--office` | Install LibreOffice |
| `--apt-install PACKAGE` | Install package via apt |
| `--flatpak-install PACKAGE` | Install package via flatpak |
| `--dark` | Configure dark theme |
| `--workspace PATH` | Workspace isolation for this setup |

## Development Flags

| Flag | Description |
|------|-------------|
| `--ruby` | Install Ruby + Bundler from apt packages |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install latest Go |
| `--python` | Install Python aliases + uv |
| `--workspace PATH` | Workspace isolation for this setup |

## Hosted Proxmox Guest Flags

Use these flags with `infra_tools.py setup ...` to create a Proxmox guest before the normal setup flow continues against that new machine. VM is now the default for `workstation_desktop`, `workstation_dev`, `pc_dev`, `server_web`, and `--build-server`; pass `--machine unprivileged` to stay on the LXC path.

| Flag | Description |
|------|-------------|
| `--hosted HOST` | Proxmox node IP/hostname, or a registered Proxmox host name from the workspace registry |
| `--hosted-user USER` | SSH user for the Proxmox node (default: `root`) |
| `--hosted-key PATH` | SSH key for the Proxmox node |
| `--memory SIZE` | Hosted guest memory, such as `2G` or `512M` |
| `--storage root POOL AMOUNT` | Required root filesystem storage spec; `POOL` may be a Proxmox storage name or `auto` |
| `--storage root AMOUNT` | Shorthand root storage spec that reuses a saved host default pool and otherwise falls back to `auto` |
| `--storage template POOL` | Optional LXC-only template storage spec; use to force where the base image is downloaded |
| `--storage template` | LXC shorthand that reuses the saved/default template storage pool |
| `--cores N` | Hosted guest vCPU count (default: `1`) |
| `--base NAME` | Base template/image family to download, such as `debian` or `ubuntu` (default: `debian`) |
| `--workspace PATH` | Workspace isolation for this setup |

Notes:

- `--storage` is repeatable and storage types are unique.
- `root` storage is required when `--hosted` is used.
- If `--hosted` matches a registered Proxmox host, infra_tools reuses that host's saved SSH key and probed storage defaults.
- `template` storage is LXC-only; if omitted, the tool prefers the root pool when it supports templates and otherwise auto-selects a template-capable pool.
- VM-first hosted flows expect an image-capable root pool such as `local-lvm`.

Full example:

```bash
python3 infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted pve1 \
  --memory 4G \
  --storage root 32G \
  --cores 2 \
  --base debian \
  --name web-01-vm \
  --ruby --node --ssl --ssl-email admin@example.com \
  --workspace /workspace/myapp \
  --deploy example.com https://github.com/user/repo.git
```

## Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy repository to domain. `GIT_URL` can be a local directory path or a git URL |
| `--full-deploy` | Always rebuild deployments (don't skip unchanged) |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email EMAIL` | Email for SSL registration |
| `--cloudflare` | Configure Cloudflare Tunnel. Generated nginx sites do not redirect HTTP to HTTPS because cloudflared connects to the origin over HTTP |
| `--api-subdomain` | Deploy Rails API to subdomain (`api.domain.com`) instead of subdirectory (`domain.com/api`) |
| `--workspace PATH` | Workspace isolation for this setup |

## Game Lobby Server (Antistatic)

Deploys the [antistatic-server](https://github.com/bluehexagons/antistatic-server) Go binary. With a hostname, infra_tools configures nginx as a reverse proxy. With a hostless spec such as `:8080`, the service listens directly on that port and no nginx site is generated.

`antistatic-db` is also supported through the same release-binary flow. The repo does not publish releases yet, but infra_tools expects future assets named `antistatic-db-linux-amd64` / `antistatic-db-linux-arm64` from `github.com/bluehexagons/antistatic-db/releases`.

| Flag | Description |
|------|-------------|
| `--antistatic-server [DOMAIN][:PORT]` | Deploy lobby server. DOMAIN is optional. PORT defaults to 8080. Hostless specs like `:8080` or `8080` listen directly without nginx. |
| `--antistatic-db [DOMAIN][:PORT]` | Deploy antistatic-db. DOMAIN is optional. PORT defaults to 8081. Hostless specs like `:8081` or `8081` listen directly without nginx. SQLite data lives in `/var/lib/antistatic-db/antistatic.db`. |

```bash
# Basic usage (default port 8080)
python3 infra_tools.py setup server_lite 192.168.1.10 --antistatic-server lobby.example.com

# With custom port
python3 infra_tools.py setup server_web 192.168.1.10 --antistatic-server lobby.example.com:9090 --ssl

# Hostless direct port, no nginx virtual host
python3 infra_tools.py setup server_lite 192.168.1.10 --antistatic-server :8080

# Deploy antistatic-db
python3 infra_tools.py setup server_web 192.168.1.10 --antistatic-db db.example.com --ssl
```

The services run as locked-down systemd units (`antistatic.service` and `antistatic-db.service`) with `Restart=on-failure`, security hardening (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`), and optional nginx configuration when a hostname is provided.

## Build/App Server Flags

| Flag | Description |
|------|-------------|
| `--build-server` | Configure as a build server that deploys to app servers |
| `--app-server` | Configure as an app server to receive deployments |
| `--deploy-target HOST` | Target app server for deployments (can be used multiple times) |

## Samba Flags

| Flag | Description |
|------|-------------|
| `--samba` | Install and configure Samba |
| `--share TYPE NAME PATHS USERS` | Configure a Samba share with comma-separated `username` or `username:password` user entries |
| `--credential USERNAME PASSWORD` | Define a password for username-only `--share` user entries |
| `--smbclient` | Install SMB/CIFS client |
| `--mount-smb MOUNT IP CREDS SHARE` | Mount SMB share persistently |

Example:

```bash
python3 infra_tools.py setup server_lite 192.168.1.10 \
  --samba \
  --credential mediauser supersecret \
  --share read media /mnt/data/media mediauser,guest:guest
```

Each bare username in `USERS` must have a matching `--credential USERNAME PASSWORD` entry.

## Sync Flags

| Flag | Description |
|------|-------------|
| `--sync SOURCE DEST INTERVAL` | Configure rsync sync |

## Data Integrity Flags

| Flag | Description |
|------|-------------|
| `--scrub DIR DBPATH REDUNDANCY FREQ` | Configure par2 integrity checking |

## Notification Flags

| Flag | Description |
|------|-------------|
| `--notify TYPE TARGET` | Configure notifications (webhook or email) |

## Saved Configuration Commands

```bash
infra_tools.py patch <host> [options]          # Patch/update an existing system
infra_tools.py list [pattern] [--json]         # List saved configurations; --json for scripting
infra_tools.py info [pattern] [--compact]      # Show configuration details; --compact for one-liners
infra_tools.py cmd [pattern]                   # Show reconstructed command
infra_tools.py rm <pattern>                    # Remove configurations
infra_tools.py deploy <pattern> [--yes]        # Redeploy systems
```

## Network Inventory and Planning

Use `infra_tools.py network` to keep a workspace-backed inventory of management
sources, control-plane addresses, guest networks, subnets, VLAN-tagged subnets,
and tagged hosts, then generate a read-only Proxmox control-plane lockdown plan.

```bash
# Inventory
infra_tools.py network list
infra_tools.py network show <profile> [--json]
infra_tools.py network init <profile> [--management CIDR] [--control-plane CIDR] [--guest-network CIDR]
infra_tools.py network add-host <profile> <name> <address> [--provider NAME] [--role ROLE]

# Proxmox imports
infra_tools.py network import-proxmox <profile> [--host NAME] [--tag TAG] [--no-control-plane]
infra_tools.py network import-proxmox-guests <profile> [--host NAME] [--tag TAG]

# Read-only planning
infra_tools.py network plan-proxmox <profile> [--json]
infra_tools.py network plan-proxmox <profile> --proxmox
```

Notes:

- The inventory lives at `<workspace>/network_inventory.json` with mode `0600`.
- Pass `--workspace PATH` immediately after `network` to isolate profiles for a project or environment.
- `plan-proxmox` is read-only: it prints an abstract plan, or with `--proxmox` renders reviewable snippets for `/etc/pve/firewall/cluster.fw`, `/etc/pve/nodes/<node>/host.fw`, and `/etc/pve/firewall/<VMID>.fw`.
- The planner returns a non-zero status until at least one management source and one control-plane address are present.

## Proxmox Management

Register Proxmox hosts and manage their VMs or LXC compatibility guests:

```bash
# Host registry
infra_tools.py proxmox add <name> <address> [--user USER] [--key PATH]
infra_tools.py proxmox probe <host>
infra_tools.py proxmox probe-cluster <address> [--user USER] [--key PATH] [--tag TAG]
infra_tools.py proxmox rolling-update <target> [<target> ...] [--dry-run] [--reboot-timeout SECONDS]
infra_tools.py proxmox hosts
infra_tools.py proxmox remove <name>

# Guest lifecycle
infra_tools.py proxmox ls <host>
infra_tools.py proxmox status <host> <vmid>
infra_tools.py proxmox start <host> <vmid>
infra_tools.py proxmox stop <host> <vmid> [--force]
infra_tools.py proxmox destroy <host> <vmid> [-y] [--force]
infra_tools.py proxmox health <host> <vmid> [--no-ssh]

# Guest configuration
infra_tools.py proxmox config <host> <vmid> [--pending]
infra_tools.py proxmox reconfigure <host> <vmid> --set KEY=VALUE [--set ...]
infra_tools.py proxmox modify <host> <vmid> [--cores N] [--memory N[M|G]]
infra_tools.py proxmox resize-disk <host> <vmid> <volume> <size>

# Notifications
infra_tools.py proxmox notifications install-webhook <host> <url> [--send-test]
infra_tools.py proxmox notifications test-webhook <host>

# Interactive shell
infra_tools.py proxmox [shell]
```

`config` shows the running guest configuration from `pct` or `qm`, and `--pending` shows changes that take effect on next restart.
`probe` caches bridge, gateway, DNS, and storage-pool recommendations back into the host registry so later `setup --hosted`
commands can reuse them.
`probe-cluster` starts from one reachable node IP/hostname, discovers every cluster member using Proxmox's configured node names,
and seeds host records for the whole cluster in one step. `--tag` is repeatable and applies those tags to newly discovered nodes.
`rolling-update` uses each target's saved setup command, rehydrates workspace credentials before patching, stops on the first
failure, and only reboots a node when `/var/run/reboot-required` exists.
`modify` and `reconfigure` changes to a running guest are queued as pending by Proxmox.
Mutating Proxmox subcommands such as `reconfigure`, `modify`, `resize-disk`, notification setup, and `rolling-update`
accept `--dry-run` to print or validate the planned work without executing it.

## Interactive Shell

```bash
infra_tools.py shell
```

Opens a REPL for browsing and managing saved configurations. Accepts the same `--workspace PATH` flag
as other commands. Available commands inside the shell:

```
list [pattern] [--json]    list saved configurations
info [pattern] [--compact] show configuration details
cmd [pattern]              show reconstructed setup command
new / setup                guided flow to create a new saved setup
deploy <pattern> [--yes]   redeploy saved configurations
rm <pattern> [--yes]       remove saved configurations
recall <host> [user]       fetch a setup command from a remote host
reconstruct [--compact]    analyze this host and print a setup summary
proxmox                    drop into the Proxmox sub-shell
workspace [path]           show or switch the active workspace
help                       show available commands
quit / exit                leave the shell
```

The shell loads `~/.infra_toolsrc` on startup. Put any commands to run at the start of each session
there — for example `workspace /path/to/project`. Command history is persisted at
`~/.local/share/infra_tools/shell_history`.

`new` / `setup` is a lightweight guided wizard: it can reuse an existing saved
setup as a starting point, optionally choose a registered Proxmox host, then
prompt for common fields such as name, IP/hostname, machine type, system type,
and a few common workstation or web-server options before saving the result.

## Utility Commands

```bash
infra_tools.py recall <host> [username]         # Read stored config or reconstruct remotely
infra_tools.py reconstruct [--compact/-c]        # Analyze the current host and emit JSON
infra_tools.py completions --shell zsh           # Install shell completion
infra_tools.py python-tools --shell bash         # Install local python alias, uv, and argcomplete
                                                   # (alias: admin-python)
sudo python3 infra_tools.py bootstrap --user admin  # Install local packages and configure tools
```
