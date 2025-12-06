# infra_tools

Automated setup scripts for remote Linux systems.

## Scripts

- `setup_workstation_desktop.py` - Desktop workstation with RDP
- `setup_workstation_dev.py` - Dev workstation with RDP (no audio, VS Code + Vivaldi)
- `setup_server_dev.py` - Development server (no desktop)
- `setup_server_web.py` - Web server with nginx (static content & reverse proxy)
- `setup_server_proxmox.py` - Proxmox server hardening
- `setup_steps.py` - Run custom steps only

## Requirements

- Python 3.9+
- SSH root access to target host
- Supported OS: Debian, Ubuntu

## Usage

```bash
# Workstation with desktop/RDP
python3 setup_workstation_desktop.py <ip> [username] [-k key] [-p password] [-t timezone] [--skip-audio]

# Workstation dev (no audio, Vivaldi + VS Code)
python3 setup_workstation_dev.py <ip> [username] [-k key] [-p password] [-t timezone]

# Development server
python3 setup_server_dev.py <ip> [username] [-k key] [-p password] [-t timezone]

# Web server
python3 setup_server_web.py <ip> [username] [-k key] [-p password] [-t timezone]

# Proxmox server hardening
python3 setup_server_proxmox.py <ip> [-k key] [-t timezone]

# Custom steps only
python3 setup_steps.py <ip> [username] --steps "install_ruby install_node" [-k key] [-p password] [-t timezone]
```

## Optional Flags

All setup scripts support optional software installation:

- `--ruby` - Install rbenv + latest Ruby version + bundler
- `--go` - Install latest Go version
- `--node` - Install nvm + latest Node.js LTS + PNPM + NPM (latest)

Example:
```bash
python3 setup_server_dev.py 192.168.1.100 --ruby --go --node
```

## Features

**Workstation Desktop:**
- XFCE desktop + xRDP + audio
- Desktop apps: LibreOffice, Brave, VSCodium, Discord
- fail2ban for RDP

**Workstation Dev:**
- XFCE desktop + xRDP (no audio)
- Desktop apps: Vivaldi, Visual Studio Code
- fail2ban for RDP

**Server Dev:**
- CLI tools only (no desktop/RDP)

**Server Web:**
- nginx with security hardened settings
- HTTP/HTTPS enabled
- Static content & reverse proxy only (no scripting)
- Hello World test page

**Server Proxmox:**
- SSH & kernel hardening
- Automatic security updates
- Preserves Proxmox firewall and cluster functionality

**All:**
- User setup with sudo
- Firewall + SSH hardening
- Auto security updates
- NTP time sync
- CLI tools: neovim, btop, htop, curl, wget, git, tmux

## Direct Execution

Scripts are installed to `/opt/infra_tools/` on the remote host:

```bash
# Run with system type
python3 /opt/infra_tools/remote_setup.py --system-type <type> --username <user> [--password <pass>] [--timezone <tz>] [--skip-audio]

# Run specific steps only
python3 /opt/infra_tools/remote_setup.py --steps "install_ruby install_go" --username <user>
```

System types: `workstation_desktop`, `workstation_dev`, `server_dev`, `server_web`, `server_proxmox`

Available steps: `install_ruby`, `install_go`, `install_node`, `install_cli_tools`, `setup_user`, `configure_firewall`, etc.

## License

Apache License 2.0
