# infra_tools

Automated setup scripts for remote Linux systems.

## Scripts

- `setup_workstation_desktop.py` - Desktop workstation with RDP
- `setup_server_dev.py` - Development server (no desktop)

## Requirements

- Python 3.9+
- SSH root access to target host
- Supported OS: Debian, Ubuntu, Fedora

## Usage

```bash
# Workstation with desktop/RDP
python3 setup_workstation_desktop.py <ip> [username] [-k key] [-p password] [-t timezone] [--skip-audio]

# Development server
python3 setup_server_dev.py <ip> [username] [-k key] [-p password] [-t timezone]
```

## Features

**Workstation Desktop:**
- XFCE desktop + xRDP + audio
- Desktop apps: LibreOffice, Brave, VSCodium, Discord
- fail2ban for RDP

**Server Dev:**
- CLI tools only (no desktop/RDP)

**Both:**
- User setup with sudo
- Firewall + SSH hardening
- Auto security updates
- NTP time sync
- CLI tools: neovim, btop, htop, curl, wget, git, tmux

## Direct Execution

Scripts are installed to `/opt/infra_tools/` on the remote host:

```bash
python3 /opt/infra_tools/remote_setup.py <system_type> [username] [password] [timezone] [skip_audio]
```

System types: `workstation_desktop`, `server_dev`

## License

Apache License 2.0
