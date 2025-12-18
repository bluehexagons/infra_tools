# infra_tools

Automated setup scripts for remote Linux systems.

## Quick Start

```bash
# Web Server (Nginx, Ruby, Node, Deploy)
python3 setup_server_web.py example.com --ruby --node --deploy example.com https://github.com/user/repo.git

# Development Workstation (Desktop, VS Code, Tools)
python3 setup_workstation_desktop.py 192.168.1.100 --desktop i3 --browser firefox

# Patch Existing System (Add features/deployments)
python3 patch_setup.py example.com --ssl --deploy api.example.com https://github.com/user/api.git
```

## System Types

| Script | Description | Key Features |
|--------|-------------|--------------|
| `setup_server_web.py` | Web Server | Nginx, Reverse Proxy, SSL, Deployments |
| `setup_server_dev.py` | Dev Server | CLI Tools, No Desktop |
| `setup_workstation_desktop.py` | Desktop Workstation | RDP, Audio, Browser, VS Code |
| `setup_pc_dev.py` | PC Dev Workstation | Bare Metal, Remmina, LibreOffice |
| `setup_workstation_dev.py` | Light Dev Workstation | RDP, No Audio, VS Code |
| `setup_server_proxmox.py` | Proxmox Hardening | Security Updates, SSH Hardening |
| `setup_steps.py` | Custom | Run specific steps only |

**Common Features:** User setup, sudo, Firewall/SSH hardening, Auto-updates, Chrony (time sync), CLI tools (neovim, btop, git, tmux).

## Usage & Flags

All scripts accept IP/Hostname.

| Flag | Description |
|------|-------------|
| `--ruby` | Install rbenv + Ruby + Bundler |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install Go |
| `--desktop [xfce\|i3\|cinnamon]` | Choose desktop environment (Default: xfce) |
| `--browser [brave\|firefox\|...]` | Choose browser (Default: brave) |
| `--flatpak` | Install Flatpak support |
| `--office` | Install LibreOffice |
| `--dry-run` | Simulate execution |

### Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy [DOMAIN] [GIT_URL]` | Deploy repo to domain/path. Supports multiple. |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email [EMAIL]` | Email for SSL registration |
| `--cloudflare` | Preconfigure Cloudflare Tunnel |
| `--api-subdomain` | Deploy Rails API to `api.domain.com` instead of `domain.com/api` |

### Samba Flags

| Flag | Description |
|------|-------------|
| `--samba` | Install and configure Samba for SMB file sharing |
| `--share [read\|write] [NAME] [PATHS] [USERS]` | Configure share: access type, name, comma-separated paths, comma-separated username:password pairs. Supports multiple. |

## Samba Guide

The `--samba` flag installs Samba and configures SMB shares for file sharing. Use `--share` to define shares.

**Share Configuration:**
- **Access Type:** `read` (read-only) or `write` (read-write)
- **Share Name:** Identifier for the share
- **Paths:** Comma-separated paths to share (e.g., `/mnt/store,/data`)
- **Users:** Comma-separated username:password pairs (e.g., `guest:guest,admin:secret`)

**Examples:**

```bash
# Single read-only share
python3 setup_server_dev.py 192.168.1.10 --samba --share read store /mnt/store guest:guest

# Read and write shares for same path
python3 setup_server_dev.py 192.168.1.10 --samba \
  --share read store /mnt/store guest:guest \
  --share write store /mnt/store admin:password

# Multiple shares
python3 patch_setup.py 192.168.1.10 --samba \
  --share read public /mnt/public guest:guest,user:pass \
  --share write private /mnt/private admin:secret
```

## Deployment Guide

The `--deploy` flag automates building and serving web applications.

- **Rails**: `bundle install`, `db:migrate`, `assets:precompile`, Systemd service.
- **Node/Vite**: `npm install`, `npm run build`, Static serving.
- **Static**: Serves files directly.

**Examples:**

```bash
# Deploy Rails API to subdomain
python3 setup_server_web.py web.com --deploy web.com https://github.com/u/repo.git --api-subdomain

# Deploy multiple sites
python3 setup_server_web.py web.com \
  --deploy site1.com https://github.com/u/site1.git \
  --deploy site2.com https://github.com/u/site2.git \
  --ssl --ssl-email admin@web.com
```

## Patching & Management

Use `patch_setup.py` to update existing systems or manage saved configurations.

```bash
# Add SSL to existing server
python3 patch_setup.py web.com --ssl --ssl-email me@web.com

# List saved configurations
python3 patch_setup.py list [pattern]

# Show configuration details
python3 patch_setup.py info [pattern]

# Remove saved configurations
python3 patch_setup.py rm [pattern]

# Redeploy/Patch multiple systems
python3 patch_setup.py deploy [pattern]
```

## Requirements

- Python 3.9+
- SSH root access
- OS: Debian

## License

Apache License 2.0
