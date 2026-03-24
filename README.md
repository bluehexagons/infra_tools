
# infra_tools

Automated setup scripts for remote Linux systems (Debian).

> **AI Agents:** See [`.github/ai-agents/`](.github/ai-agents/) for development guidance.
>
> **Machine Types:** See [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for environment-specific configuration.

## Quick Start

```bash
# Using unified infra_tools.py (recommended)
python3 infra_tools.py setup server_web example.com --ruby --node --deploy example.com https://github.com/user/repo.git
python3 infra_tools.py setup workstation_desktop 192.168.1.100 --desktop i3 --browser firefox
python3 infra_tools.py patch example.com --ssl --deploy api.example.com https://github.com/user/api.git

# Or use individual scripts
python3 setup_server_web.py example.com --ruby --node --deploy example.com https://github.com/user/repo.git
python3 setup_workstation_desktop.py 192.168.1.100 --desktop i3 --browser firefox
python3 patch_setup.py example.com --ssl --deploy api.example.com https://github.com/user/api.git
```

## What It Does

- **Servers**: Security hardening, Nginx/SSL, Ruby/Node/Go, app deployment
- **Workstations**: Desktop environments (XFCE, i3, LXQt), RDP, browsers, audio
- **Storage**: Samba shares, rsync sync, par2 integrity verification
- **Security**: Firewall, SSH hardening, fail2ban, auto-updates, weekly cleanup maintenance, journald size limits

Background maintenance includes a `cleanup-maintenance` systemd timer that reclaims temporary files,
old package-manager caches, and oversized journals. Infra tools also installs a journald drop-in at
`/etc/systemd/journald.conf.d/infra-tools.conf` to cap persistent and runtime journal usage at `100M`.

## Setup Scripts

| Script | Description |
|--------|-------------|
| `infra_tools.py` | **Unified entry point** - Use `setup` or `patch` subcommands for all operations |
| `setup_server_web.py` | Web server with Nginx, reverse proxy, SSL, deployments |
| `setup_server_dev.py` | Development server with CLI tools |
| `setup_workstation_desktop.py` | Desktop workstation with RDP, browsers |
| `setup_admin_python.py` | Local user installer for Python aliases, uv, and shell completion |
| `patch_setup.py` | Update existing systems, manage saved configurations |
| `recall_setup.py` | Retrieve configuration from remote host |

**Recommendation**: Use `infra_tools.py` as your primary entry point. It provides a consistent interface for both initial setup and patching operations.

See [Command-Line Reference](./docs/COMMAND_LINE.md) for all flags.

## Common Examples

### Web Server with Deployment
```bash
# Using unified tool
python3 infra_tools.py setup server_web web.com \
  --ruby --node \
  --ssl --ssl-email admin@web.com \
  --deploy web.com https://github.com/user/repo.git

# Or use individual script
python3 setup_server_web.py web.com \
  --ruby --node \
  --ssl --ssl-email admin@web.com \
  --deploy web.com https://github.com/user/repo.git
```

### Remote Desktop Workstation
```bash
# Using unified tool
python3 infra_tools.py setup workstation_desktop 192.168.1.50 \
  --desktop xfce --rdp --audio \
  --browser librewolf \
  --ruby --node

# Or use individual script
python3 setup_workstation_desktop.py 192.168.1.50 \
  --desktop xfce --rdp --audio \
  --browser librewolf \
  --ruby --node
```

### NAS with Backup
```bash
# Using unified tool
python3 infra_tools.py setup server_lite 192.168.1.10 \
  --samba \
  --credential guest guest \
  --share read media /mnt/data/media guest \
  --sync /mnt/data/docs /mnt/backup daily \
  --scrub /mnt/backup .pardatabase 5% weekly

# Or use individual script
python3 setup_server_lite.py 192.168.1.10 \
  --samba \
  --credential guest guest \
  --share read media /mnt/data/media guest \
  --sync /mnt/data/docs /mnt/backup daily \
  --scrub /mnt/backup .pardatabase 5% weekly
```

### Hosted Proxmox LXC
```bash
# Create an LXC on Proxmox, then run the normal web-server setup against it
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
  --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

`--storage` is repeatable: `root` is required as `--storage root POOL AMOUNT`, and `template` is optional as `--storage template POOL`.

Use `--credential USERNAME PASSWORD` to define share passwords once, then reference those users by name in
`--share`. The `USERS` field accepts a comma-separated list of `username` or `username:password` entries, and
each bare username must have a matching `--credential`.

## Requirements

- Python 3.9+
- SSH root access to target system
- Target OS: Debian

## Shell Completion

Setup scripts support tab completion for bash, zsh, and fish.

```bash
uv tool install --upgrade argcomplete
python3 setup_completions.py
```

See [docs/SHELL_COMPLETION.md](docs/SHELL_COMPLETION.md) for detailed setup.

## Testing

```bash
python3 -m pytest tests/ -v
```

## License

Apache License 2.0
