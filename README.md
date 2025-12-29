# infra_tools

Automated setup scripts for remote Linux systems (Debian).

## Quick Start

```bash
python3 setup_server_web.py example.com --ruby --node --deploy example.com https://github.com/user/repo.git
python3 setup_workstation_desktop.py 192.168.1.100 --desktop i3 --browser firefox
python3 patch_setup.py example.com --ssl --deploy api.example.com https://github.com/user/api.git
```

## Setup Scripts

| Script | Description |
|--------|-------------|
| `setup_server_web.py` | Web server with Nginx, reverse proxy, SSL, deployments |
| `setup_server_dev.py` | Development server with CLI tools, no desktop |
| `setup_server_lite.py` | Minimal server setup without interactive CLI tools |
| `setup_workstation_desktop.py` | Desktop workstation with RDP, browser, VS Code (audio via --audio) |
| `setup_pc_dev.py` | PC dev workstation with bare metal, Remmina, LibreOffice (audio via --audio) |
| `setup_workstation_dev.py` | Light dev workstation with RDP, VS Code (audio via --audio) |
| `setup_server_proxmox.py` | Proxmox hardening with security updates, SSH hardening |
| `setup_steps.py` | Custom setup, run specific steps only |

Common features: User setup, sudo, firewall/SSH hardening, auto-updates, Chrony, CLI tools (neovim, btop, git, tmux).

## Command-Line Flags

### Basic Flags

| Flag | Description |
|------|-------------|
| `host` | IP address or hostname (positional argument) |
| `username` | Username (positional, optional, defaults to current user) |
| `-k, --key PATH` | SSH private key path |
| `-p, --password PASS` | User password |
| `-t, --timezone TZ` | Timezone (defaults to UTC) |
| `--name NAME` | Friendly name for this configuration |
| `--tags TAG1,TAG2` | Comma-separated tags for this configuration |
| `--dry-run` | Simulate execution without making changes |

### Desktop/Workstation Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable/disable RDP/XRDP (default: enabled for workstation setups) |
| `--x2go` / `--no-x2go` | Enable/disable X2Go remote desktop |
| `--audio` / `--no-audio` | Enable/disable audio setup (desktop only) |
| `--desktop [xfce\|i3\|cinnamon]` | Desktop environment (default: xfce) |
| `--browser [brave\|firefox\|browsh\|vivaldi\|lynx]` | Web browser (default: brave) |
| `--flatpak` | Install desktop apps via Flatpak |
| `--office` | Install LibreOffice (default: enabled for pc_dev) |

### Development Flags

| Flag | Description |
|------|-------------|
| `--ruby` | Install rbenv + latest Ruby + Bundler |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install latest Go |
| `--steps STEP1 STEP2` | Run specific custom steps (for setup_steps.py) |

### Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy repository to domain/path (can use multiple times) |
| `--full-deploy` | Always rebuild deployments (default: skip unchanged) |
| `--ssl` | Enable Let's Encrypt SSL/TLS certificates |
| `--ssl-email EMAIL` | Email for SSL registration (optional) |
| `--cloudflare` | Preconfigure Cloudflare Tunnel (disables public HTTP/HTTPS ports) |
| `--api-subdomain` | Deploy Rails API to api.domain.com instead of domain.com/api |

### Samba Flags

| Flag | Description |
|------|-------------|
| `--samba` | Install and configure Samba for SMB file sharing |
| `--share TYPE NAME PATHS USERS` | Configure Samba share (can use multiple times): TYPE (read or write), NAME (share name), PATHS (comma-separated paths), USERS (comma-separated username:password pairs) |
| `--smbclient` | Install SMB/CIFS client packages for connecting to network shares (default: enabled for pc_dev). Enables file managers to browse SMB/Samba shares. |
| `--mount-smb MOUNT IP CREDS SHARE SUBDIR` | Mount SMB share persistently (can use multiple times): MOUNT (/mnt/path), IP (ip_address), CREDS (username:password), SHARE (share_name), SUBDIR (/share/subdirectory). Auto-enables --smbclient. Uses systemd automount with nofail for resilience. |

### Sync Flags

| Flag | Description |
|------|-------------|
| `--sync SOURCE DEST INTERVAL` | Configure directory synchronization with rsync (can use multiple times): SOURCE (source directory), DEST (destination directory), INTERVAL (hourly, daily, weekly, or monthly). Creates systemd timer for automated incremental backups. Checks mount availability if paths are on SMB mounts. |

## Deployment Guide

The `--deploy` flag automates building and serving web applications:

- **Rails**: `bundle install`, `db:migrate`, `assets:precompile`, Systemd service
- **Node/Vite**: `npm install`, `npm run build`, static serving
- **Static**: Direct file serving

**Examples:**

```bash
# Single deployment
python3 setup_server_web.py web.com --deploy web.com https://github.com/user/repo.git

# Multiple sites with SSL
python3 setup_server_web.py web.com \
  --deploy site1.com https://github.com/user/site1.git \
  --deploy site2.com https://github.com/user/site2.git \
  --ssl --ssl-email admin@web.com

# Rails API as subdomain
python3 setup_server_web.py api.com --deploy api.com https://github.com/user/api.git --api-subdomain
```

## Samba Guide

Configure SMB file sharing with security hardening, firewall rules, and fail2ban protection.

**Examples:**

```bash
# Single read-only share
python3 setup_server_dev.py 192.168.1.10 --samba --share read store /mnt/store guest:guest

# Read and write shares for same path with different users
python3 setup_server_dev.py 192.168.1.10 --samba \
  --share read store /mnt/store guest:guest \
  --share write store /mnt/store admin:password

# Multiple shares
python3 patch_setup.py 192.168.1.10 --samba \
  --share read public /mnt/public guest:guest,user:pass \
  --share write private /mnt/private admin:secret
```

## Patch Setup

Use `patch_setup.py` to update existing systems or manage saved configurations.

```bash
# Add SSL to existing server
python3 patch_setup.py web.com --ssl --ssl-email me@web.com

# List saved configurations (filter by host/name/tag)
python3 patch_setup.py list [pattern]

# Show configuration details
python3 patch_setup.py info [pattern]

# Remove saved configurations
python3 patch_setup.py rm [pattern]

# Redeploy/patch multiple systems matching pattern
python3 patch_setup.py deploy [pattern]
```

Pattern matching is case-insensitive and searches hosts, names, and tags.

## Requirements

- Python 3.9+
- SSH root access to target system
- Target OS: Debian

## License

Apache License 2.0
