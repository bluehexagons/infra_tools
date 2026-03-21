# Command-Line Reference

Complete reference for all setup script flags.

## Unified Entry Point (Recommended)

The `infra_tools.py` script provides a unified interface for all operations:

```bash
# Setup a new system
infra_tools.py setup <system_type> <host> [username] [options]

# Patch/update an existing system  
infra_tools.py patch <host> [username] [options]
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

# Provision a hosted LXC on a Proxmox node, then configure it as a web server
infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted 10.0.0.10 \
  --hosted-user root \
  --hosted-key ~/.ssh/proxmox_ed25519 \
  --memory 4G \
  --storage root auto 20G \
  --storage template local \
  --cores 2 \
  --base debian \
  --name web-01 \
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
| `--machine TYPE` | Machine type: `unprivileged` (LXC, default), `vm`, `privileged`, `hardware`, `oci` |
| `--name NAME` | Friendly name for this configuration |
| `--tags TAG1,TAG2` | Comma-separated tags for this configuration |
| `--dry-run` | Simulate execution without making changes |

## Desktop/Workstation Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable/disable RDP/XRDP (default: enabled for workstations) |
| `--audio` / `--no-audio` | Enable/disable audio setup |
| `--desktop [xfce\|i3\|cinnamon\|lxqt]` | Desktop environment (default: xfce) |
| `--browser NAME` | Browser to install (can be used multiple times) |
| `--flatpak` | Install desktop apps via Flatpak |
| `--office` | Install LibreOffice |
| `--apt-install PACKAGE` | Install package via apt |
| `--flatpak-install PACKAGE` | Install package via flatpak |
| `--dark` | Configure dark theme |

## Development Flags

| Flag | Description |
|------|-------------|
| `--ruby` | Install Ruby + Bundler from apt packages |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install latest Go |
| `--python` | Install Python aliases + uv |

## Hosted Proxmox LXC Flags

Use these flags with `infra_tools.py setup ...` or the legacy `setup_*.py` scripts to create an LXC container on a Proxmox host before the normal setup flow continues against that new container.

| Flag | Description |
|------|-------------|
| `--hosted HOST` | Proxmox node IP or hostname where the container will be created |
| `--hosted-user USER` | SSH user for the Proxmox node (default: `root`) |
| `--hosted-key PATH` | SSH key for the Proxmox node |
| `--memory SIZE` | Container memory, such as `2G` or `512M` |
| `--storage root POOL AMOUNT` | Required root filesystem storage spec; `POOL` may be a Proxmox storage name or `auto` |
| `--storage template POOL` | Optional template storage spec; use to force where the base image is downloaded |
| `--cores N` | Container vCPU count (default: `1`) |
| `--base NAME` | Base template family to download, such as `debian` or `ubuntu` (default: `debian`) |

Notes:

- `--storage` is repeatable and storage types are unique.
- `root` storage is required when `--hosted` is used.
- `template` storage is optional; if omitted, the tool prefers the root pool when it supports templates and otherwise auto-selects a template-capable pool.

Full example:

```bash
python3 infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted 10.0.0.10 \
  --hosted-user root \
  --hosted-key ~/.ssh/proxmox_ed25519 \
  --memory 4G \
  --storage root auto 20G \
  --storage template local \
  --cores 2 \
  --base debian \
  --name web-01 \
  --ruby --node --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

## Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy repository to domain |
| `--full-deploy` | Always rebuild deployments |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email EMAIL` | Email for SSL registration |
| `--cloudflare` | Configure Cloudflare Tunnel |
| `--api-subdomain` | Deploy Rails API to subdomain |

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
python3 setup_server_lite.py 192.168.1.10 \
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

## Patch Commands

When using `infra_tools.py patch` or the legacy `patch_setup.py`:

```bash
infra_tools.py patch <host> [options]     # Using unified tool

# Legacy commands still work:
patch_setup.py list [pattern]             # List saved configurations
patch_setup.py info [pattern]             # Show configuration details
patch_setup.py cmd [pattern]              # Show reconstructed command
patch_setup.py rm [pattern]               # Remove configurations
patch_setup.py deploy [pattern]           # Redeploy systems
```
