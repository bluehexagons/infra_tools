# infra_tools

Automated setup scripts for remote Linux systems.

## Scripts

- `setup_workstation_desktop.py` - Desktop workstation with RDP
- `setup_pc_dev.py` - PC development workstation (bare hardware, includes Remmina + LibreOffice by default)
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

# PC development workstation (bare hardware, Remmina + LibreOffice by default)
python3 setup_pc_dev.py <ip> [username] [-k key] [-p password] [-t timezone] [--skip-audio]

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

Desktop workstation scripts support desktop environment and browser selection:

- `--desktop [xfce|i3|cinnamon]` - Choose desktop environment (default: xfce)
- `--browser [brave|firefox|browsh|vivaldi|lynx]` - Choose web browser (default: brave)
  - Firefox: Installs with uBlock Origin extension
  - Browsh: Requires Firefox (text-based browser)
- `--flatpak` - Install desktop apps via Flatpak (for non-containerized environments)
- `--office` - Install LibreOffice (desktop only, not installed by default except for pc_dev)
- `--dry-run` - Show what would be done without executing commands

Example:
```bash
# Install Ruby, Go, and Node.js on a dev server
python3 setup_server_dev.py 192.168.1.100 --ruby --go --node

# Install i3 window manager instead of XFCE on a workstation
python3 setup_workstation_desktop.py 192.168.1.100 --desktop i3

# Use Firefox instead of Brave
python3 setup_workstation_desktop.py 192.168.1.100 --browser firefox

# Use Flatpak for desktop apps with Vivaldi browser and LibreOffice
python3 setup_workstation_dev.py 192.168.1.100 --flatpak --browser vivaldi --office

# PC Dev setup (LibreOffice installed by default)
python3 setup_pc_dev.py 192.168.1.100

# Dry-run to see what would be done
python3 setup_workstation_desktop.py 192.168.1.100 --dry-run
```

## Features

**Workstation Desktop:**
- Desktop environment (XFCE, i3, or Cinnamon) + xRDP + audio
- Browser (Brave, Firefox, Vivaldi, Lynx, or Browsh)
- Desktop apps: VSCodium, Discord
- Optional: LibreOffice (with --office flag)
- fail2ban for RDP

**PC Dev:**
- Desktop environment (XFCE, i3, or Cinnamon) + xRDP + audio
- Browser (Brave, Firefox, Vivaldi, Lynx, or Browsh)
- Desktop apps: VSCodium, Discord, Remmina RDP client
- LibreOffice (installed by default)
- Designed for bare hardware development PCs
- fail2ban for RDP

**Workstation Dev:**
- Desktop environment (XFCE, i3, or Cinnamon) + xRDP (no audio)
- Browser (Brave, Firefox, Vivaldi, Lynx, or Browsh)
- Desktop apps: Visual Studio Code
- Optional: LibreOffice (with --office flag)
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

System types: `workstation_desktop`, `pc_dev`, `workstation_dev`, `server_dev`, `server_web`, `server_proxmox`

Available steps: `install_ruby`, `install_go`, `install_node`, `install_cli_tools`, `setup_user`, `configure_firewall`, etc.

## License

Apache License 2.0
