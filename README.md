
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

Setup scripts support tab completion for bash, zsh, and fish.

```bash
pip install argcomplete
python3 setup_completions.py
```

See [docs/SHELL_COMPLETION.md](docs/SHELL_COMPLETION.md) for detailed setup.

## Testing

```bash
python3 -m pytest tests/ -v
```

## License

Apache License 2.0
