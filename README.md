
# infra_tools

Automated setup scripts for remote Linux systems (Debian).

> **AI Agents:** See [`.github/ai-agents/`](.github/ai-agents/) for development guidance.
>
> **Machine Types:** See [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for environment-specific configuration.

## Quick Start

```bash
python3 infra_tools.py setup server_web example.com admin --ruby --node --deploy example.com https://github.com/user/repo.git
python3 infra_tools.py setup workstation_desktop 192.168.1.100 admin --desktop i3 --browser firefox
python3 infra_tools.py patch example.com admin --ssl --deploy api.example.com https://github.com/user/api.git
python3 infra_tools.py credentials set guest s3cret
```

## What It Does

- **Servers**: Security hardening, Nginx/SSL, Ruby/Node/Go, app deployment, game lobby server
- **Workstations**: Desktop environments (XFCE, i3, LXQt), RDP, browsers, audio
- **Storage**: Samba shares, rsync sync, par2 integrity verification
- **Security**: Firewall, SSH hardening, fail2ban, auto-updates, weekly cleanup maintenance, journald size limits

Background maintenance includes a `cleanup-maintenance` systemd timer that reclaims temporary files,
old package-manager caches, and oversized journals. Infra tools also installs a journald drop-in at
`/etc/systemd/journald.conf.d/infra-tools.conf` to cap persistent and runtime journal usage at `100M`.

## CLI Entry Points

| Script | Description |
|--------|-------------|
| `infra_tools.py` | **Unified entry point** - Use `setup`, `patch`, `list`, `info`, `cmd`, `rm`, `deploy`, `recall`, `reconstruct`, `completions`, `python-tools`, `bootstrap`, `credentials`, or `proxmox` |

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
python3 infra_tools.py setup workstation_desktop user192.168.1.100 --desktop i3 --browser firefox
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

### Managing Proxmox Containers

Register Proxmox hosts and manage their LXC containers from a workspace registry. Run with no
subcommand to enter an interactive shell, or use the subcommands directly:

```bash
python3 infra_tools.py proxmox add pve1 10.0.0.10 --user root --ssh-key ~/.ssh/proxmox_ed25519
python3 infra_tools.py proxmox ls pve1
python3 infra_tools.py proxmox health pve1 101
python3 infra_tools.py proxmox stop pve1 101
python3 infra_tools.py proxmox destroy pve1 101 -y
python3 infra_tools.py proxmox notifications install-webhook pve1 https://notify.example/hook --send-test
python3 infra_tools.py proxmox shell
```

The registry is stored at `<workspace>/proxmox_hosts.json` (mode `0600`).
Proxmox notifications use the native Proxmox webhook endpoint and matcher
configuration via `pvesh` (no local hook script); the generated payload follows
the infra_tools notification JSON shape.

### Tests

Run the full default suite (fast — no network, no live hosts):

```bash
python3 -m unittest discover -s tests   # raw unittest
./run_tests.py                          # nicer wrapper with selectors
./run_tests.py --list-suites            # named slices: smoke, proxmox, security, integration
./run_tests.py --suite smoke            # quick high-value checks
./run_tests.py --suite proxmox          # all Proxmox tests (live test still gated)
./run_tests.py test_proxmox_manage      # one module
./run_tests.py --durations 20           # show slowest tests
./run_tests.py -v                       # verbose
```

Expensive tests (live Proxmox round-trips, network downloads, slow tests) are
gated behind opt-in *categories*. List them and run them on demand:

```bash
./run_tests.py --list-categories
./run_tests.py --check-prereqs --expensive live_proxmox
./run_tests.py --expensive live_proxmox tests.test_proxmox_live
./run_tests.py --expensive all          # everything, including expensive
```

Each category also has a matching env var (e.g. `INFRA_TOOLS_RUN_LIVE_PROXMOX=1`),
or set `INFRA_TOOLS_RUN_EXPENSIVE=1` to enable everything. See
[`tests/expensive_support.py`](tests/expensive_support.py) for details and
[`tests/test_proxmox_live.py`](tests/test_proxmox_live.py) for the env vars
needed to point the live Proxmox test at a real host.

Use `--credential USERNAME PASSWORD` to define share passwords once, then reference those users by username
in `--share` or `--mount-smb`. The `USERS` field accepts a comma-separated list of `username` or `username:password`
entries, and each bare username must have a matching saved credential. Use `infra_tools.py credentials set USERNAME
PASSWORD` to manage the shared workspace store directly.

### Game Lobby Server (Antistatic)
```bash
# Deploy the antistatic lobby server behind nginx (reruns upgrade to the latest GitHub release)
python3 infra_tools.py setup server_lite 192.168.1.10 --antistatic-server lobby.example.com

# With custom internal port (default: 8080)
python3 infra_tools.py setup server_web 192.168.1.10 --antistatic-server lobby.example.com:9090 --ssl

# The lobby server binary is fetched from github.com/bluehexagons/antistatic-server/releases
# Runs as a locked-down systemd service with automatic restart on failure
```

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
