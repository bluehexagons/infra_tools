
# infra_tools

Automated setup scripts for remote Linux systems (Debian).

> **AI Agents:** See [`.github/ai-agents/`](.github/ai-agents/) for development guidance.
>
> **Machine Types:** See [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for environment-specific configuration.

## Quick Start

```bash
python3 setup_server_web.py example.com --ruby --node --deploy example.com https://github.com/user/repo.git
python3 setup_workstation_desktop.py 192.168.1.100 --desktop i3 --browser firefox
python3 patch_setup.py example.com --ssl --deploy api.example.com https://github.com/user/api.git
```

## What It Does

- **Servers**: Security hardening, Nginx/SSL, Ruby/Node/Go, app deployment
- **Workstations**: Desktop environments (XFCE, i3, LXQt), RDP, browsers, audio
- **Storage**: Samba shares, rsync sync, par2 integrity verification
- **Security**: Firewall, SSH hardening, fail2ban, auto-updates

## Setup Scripts

| Script | Description |
|--------|-------------|
| `setup_server_web.py` | Web server with Nginx, reverse proxy, SSL, deployments |
| `setup_server_dev.py` | Development server with CLI tools |
| `setup_workstation_desktop.py` | Desktop workstation with RDP, browsers |
| `patch_setup.py` | Update existing systems, manage saved configurations |
| `recall_setup.py` | Retrieve configuration from remote host |

See [Command-Line Reference](./docs/COMMAND_LINE.md) for all flags.

## Common Examples

### Web Server with Deployment
```bash
python3 setup_server_web.py web.com \
  --ruby --node \
  --ssl --ssl-email admin@web.com \
  --deploy web.com https://github.com/user/repo.git
```

### Remote Desktop Workstation
```bash
python3 setup_workstation_desktop.py 192.168.1.50 \
  --desktop xfce --rdp --audio \
  --browser librewolf \
  --ruby --node
```

### NAS with Backup
```bash
python3 setup_server_lite.py 192.168.1.10 \
  --samba \
  --share read media /mnt/data/media guest:guest \
  --sync /mnt/data/docs /mnt/backup daily \
  --scrub /mnt/backup .pardatabase 5% weekly
```

## Requirements

- Python 3.9+
- SSH root access to target system
- Target OS: Debian

## Shell Completion

All setup scripts support tab completion for bash, zsh, and fish shells. This provides auto-completion for flags, options, and arguments.

### Quick Setup

```bash
# Install argcomplete
pip install argcomplete

# Enable completions for your shell
python3 setup_completions.py
```

The `setup_completions.py` script auto-detects your shell and configures completions for all infra_tools commands:
- `setup_workstation_desktop`
- `setup_workstation_dev`
- `setup_server_web`
- `setup_server_dev`
- `setup_server_proxmox`
- `setup_server_lite`
- `setup_pc_dev`
- `patch_setup`
- `recall_setup`
- `reconstruct_setup`
- `webhook_manager`

### Manual Setup

**Bash:**
```bash
eval "$(register-python-argcomplete setup_workstation_desktop)"
eval "$(register-python-argcomplete setup_server_web)"
# ... repeat for each script you use
```

**Zsh:**
```bash
eval "$(register-python-argcomplete setup_workstation_desktop)"
eval "$(register-python-argcomplete setup_server_web)"
# ... repeat for each script you use
```

**Fish:**
```bash
register-python-argcomplete --shell fish setup_workstation_desktop > ~/.config/fish/completions/setup_workstation_desktop.fish
register-python-argcomplete --shell fish setup_server_web > ~/.config/fish/completions/setup_server_web.fish
```

### System-wide Installation

For system-wide completion (requires sudo):
```bash
sudo python3 setup_completions.py --global --shell bash
```

## Testing

```bash
python3 -m pytest tests/ -v
```

## License

Apache License 2.0
