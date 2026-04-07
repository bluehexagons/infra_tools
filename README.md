
# infra_tools

Automated setup scripts for remote Linux systems (Debian).

> **AI Agents:** See [`.github/ai-agents/`](.github/ai-agents/) for development guidance.
>
> **Machine Types:** See [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for environment-specific configuration.

## Quick Start

```bash
python3 infra_tools.py setup server_web example.com --ruby --node --deploy example.com https://github.com/user/repo.git
python3 infra_tools.py setup workstation_desktop 192.168.1.100 --desktop i3 --browser firefox
python3 infra_tools.py patch example.com --ssl --deploy api.example.com https://github.com/user/api.git
python3 infra_tools.py credentials set guest s3cret
```

## What It Does

- **Servers**: Security hardening, Nginx/SSL, Ruby/Node/Go, app deployment
- **Workstations**: Desktop environments (XFCE, i3, LXQt), RDP, browsers, audio
- **Storage**: Samba shares, rsync sync, par2 integrity verification
- **Security**: Firewall, SSH hardening, fail2ban, auto-updates, weekly cleanup maintenance, journald size limits

Background maintenance includes a `cleanup-maintenance` systemd timer that reclaims temporary files,
old package-manager caches, and oversized journals. Infra tools also installs a journald drop-in at
`/etc/systemd/journald.conf.d/infra-tools.conf` to cap persistent and runtime journal usage at `100M`.

## CLI Entry Points

| Script | Description |
|--------|-------------|
| `infra_tools.py` | **Unified entry point** - Use `setup`, `patch`, `list`, `info`, `cmd`, `rm`, `deploy`, `recall`, `reconstruct`, `completions`, `python-tools`, `bootstrap`, or `credentials` |

Use `infra_tools.py` for all system setup, saved-configuration management, patching, recall, reconstruction, local Python tooling, and shell-completion setup. The legacy per-system `setup_*.py` wrappers, `patch_setup.py`, `recall_setup.py`, `reconstruct_setup.py`, `setup_admin_python.py`, and `setup_completions.py` have been removed.

See [Command-Line Reference](./docs/COMMAND_LINE.md) for all flags.

## Common Examples

### Web Server with Deployment
```bash
python3 infra_tools.py setup server_web web.com \
  --ruby --node \
  --ssl --ssl-email admin@web.com \
  --deploy web.com https://github.com/user/repo.git
```

### Remote Desktop Workstation
```bash
python3 infra_tools.py setup workstation_desktop 192.168.1.50 \
  --desktop xfce --rdp --audio \
  --browser librewolf \
  --ruby --node
```

### NAS with Backup
```bash
python3 infra_tools.py setup server_lite 192.168.1.10 \
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
`--share` or `--mount-smb`. The `USERS` field accepts a comma-separated list of `username` or `username:password`
entries, and each bare username must have a matching saved credential. Use `infra_tools.py credentials set USERNAME
PASSWORD` to manage the shared workspace store directly.

Workspace state now lives under `~/.config/infra_tools` by default. Use `--workspace /path/to/workspace` to isolate
saved setups, credentials, and history for a project or test environment.

## Requirements

- Python 3.10+
- SSH root access to target system
- Target OS: Debian

### Local Orchestration Host Bootstrap

To prepare the machine where you run `infra_tools.py`, an admin can install the local package prerequisites and
configure the chosen user's Python tooling and shell completion in one step:

```bash
sudo python3 infra_tools.py bootstrap --user "$USER"
```

## Shell Completion

The unified CLI supports tab completion for bash, zsh, and fish.

```bash
uv tool install --upgrade argcomplete
python3 infra_tools.py completions
```

See [docs/SHELL_COMPLETION.md](docs/SHELL_COMPLETION.md) for detailed setup.

## Testing

```bash
python3 -m unittest discover -s tests
```

## License

Apache License 2.0
