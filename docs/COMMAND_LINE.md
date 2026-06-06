# Command-Line Reference

Concise reference for the unified `infra_tools.py` CLI. The code help and
`lib/arg_parser.py` remain the source of truth; this doc keeps the command
surface and the non-obvious behaviors that are easy to forget.

Related pages:

- [`SYSADMIN.md`](./SYSADMIN.md) for remote host shortcuts
- [`NETWORKING.md`](./NETWORKING.md) for workspace network inventory
- [`CICD.md`](./CICD.md) for webhook CI/CD setup
- [`MACHINE_TYPES.md`](./MACHINE_TYPES.md) for machine type behavior

## Unified Entry Point

```bash
infra_tools.py setup <system_type> <host> [username] [options]
infra_tools.py patch <host> [username] [options]
infra_tools.py recall <host> [username] [options]
infra_tools.py reconstruct [--compact]
infra_tools.py list [pattern] [--json]
infra_tools.py info [pattern] [--compact]
infra_tools.py cmd [pattern]
infra_tools.py rm <pattern>
infra_tools.py deploy <pattern> [--yes]
infra_tools.py credentials set <username> <password>
infra_tools.py credentials list
infra_tools.py credentials remove <username>
infra_tools.py completions [options]
infra_tools.py python-tools [options]
infra_tools.py bootstrap [options]
infra_tools.py self-setup [options]
infra_tools.py shell
infra_tools.py network ...
infra_tools.py proxmox ...
```

## Setup At A Glance

### System Types

| Type | Description |
|------|-------------|
| `workstation_desktop` | Desktop workstation with GUI |
| `workstation_dev` | Developer workstation |
| `pc_dev` | PC development environment |
| `server_dev` | Development server |
| `server_web` | Web server |
| `server_lite` | Lightweight server |
| `server_proxmox` | Proxmox host server |

### Core Flags

| Flag | Description |
|------|-------------|
| `host` | Hostname or IP address |
| `username` | Optional SSH username |
| `-k, --key PATH` | SSH private key |
| `-p, --password PASS` | SSH password |
| `-t, --timezone TZ` | Timezone |
| `--workspace PATH` | Workspace root for config, credentials, known_hosts, and history |
| `--machine TYPE` | Machine type override |
| `--name NAME` | Friendly name for the configuration |
| `--tags TAG1,TAG2` | Comma-separated tags |
| `--dry-run` | Simulate execution |
| `--auto-restart` / `--no-auto-restart` | Control normal automatic restarts |
| `--auto-restart-force-days N` | Force restart after N days of deferrals |
| `--auto-restart-grace N` | Warning period before an automatic restart |

### Common Setup Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable or disable XRDP |
| `--audio` / `--no-audio` | Enable or disable audio setup |
| `--desktop [xfce\|i3\|cinnamon\|lxqt]` | Desktop environment |
| `--browser NAME` | Browser to install |
| `--flatpak` | Install desktop apps via Flatpak |
| `--office` | Install LibreOffice |
| `--apt-install PACKAGE` | Install a package via apt |
| `--flatpak-install PACKAGE` | Install a package via Flatpak |
| `--dark` | Configure dark theme |

### Development Flags

| Flag | Description |
|------|-------------|
| `--ruby` | Install Ruby + Bundler |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install Go |
| `--python` | Install Python aliases + uv |

### Hosted Proxmox Flags

| Flag | Description |
|------|-------------|
| `--hosted HOST` | Proxmox node or registered host name |
| `--hosted-user USER` | SSH user for the Proxmox node |
| `--hosted-key PATH` | SSH key for the Proxmox node |
| `--memory SIZE` | Guest memory |
| `--storage root POOL AMOUNT` | Required root storage spec |
| `--storage root AMOUNT` | Root storage shorthand using saved defaults or `auto` |
| `--storage template POOL` | LXC template storage spec |
| `--storage template` | LXC shorthand for the saved/default template pool |
| `--cores N` | Guest vCPU count |
| `--base NAME` | Base image family |

Notes:

- `--storage` is repeatable.
- `root` storage is required when `--hosted` is used.
- `template` storage is LXC-only.
- VM is the default for hosted `workstation_desktop`, `workstation_dev`,
  `pc_dev`, `server_web`, and build-server flows.
- `--machine unprivileged` keeps an existing or intentional LXC path.

## Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy a repository to a domain |
| `--deployment-lite` | Use cached/pre-uploaded repository files only |
| `--deployment-full` | Pull fresh repositories and rebuild everything |
| `--full-deploy` | Always rebuild deployments even if unchanged |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email EMAIL` | Email for SSL registration |
| `--cloudflare` | Configure Cloudflare Tunnel |
| `--api-subdomain` | Deploy Rails API to `api.domain.com` |

## Build / App Servers

| Flag | Description |
|------|-------------|
| `--build-server` | Configure a build server that deploys to app servers |
| `--app-server` | Configure an app server to receive deployments |
| `--deploy-target HOST` | Target app server for deployments |

## Antistatic

`--antistatic-server` and `--antistatic-db` deploy the release binaries
maintained in code. Hostname-based specs are reverse-proxied through nginx;
hostless specs such as `:8080` or `:8081` listen directly on the target port.

| Flag | Description |
|------|-------------|
| `--antistatic-server [DOMAIN][:PORT]` | Deploy the lobby server |
| `--antistatic-db [DOMAIN][:PORT]` | Deploy antistatic-db |

## Storage And Data Movement

| Flag | Description |
|------|-------------|
| `--samba` | Install and configure Samba |
| `--share TYPE NAME PATHS USERS` | Configure a Samba share |
| `--credential USERNAME PASSWORD` | Define a password for username-only share entries |
| `--smbclient` | Install SMB/CIFS client |
| `--mount-smb MOUNT IP CREDS SHARE` | Mount SMB share persistently |
| `--sync SOURCE DEST INTERVAL` | Configure rsync sync |
| `--scrub DIR DBPATH REDUNDANCY FREQ` | Configure par2 integrity checking |
| `--notify TYPE TARGET` | Configure notifications |

## Maintenance and Utilities

### GitHub Maintenance

```bash
infra_tools.py maintenance github audit --root /home/loren/repos
infra_tools.py maintenance github prune --root /home/loren/repos --yes
infra_tools.py maintenance github prune --root /home/loren/repos --delete-caches --yes
```

Defaults: keep 2 releases, delete expired artifacts, prune caches only when
`--delete-caches` is set, and treat caches as stale after 90 days.

### Network Inventory

```bash
infra_tools.py network list
infra_tools.py network init <profile> [--management CIDR] [--control-plane CIDR] [--guest-network CIDR]
infra_tools.py network add-host <profile> <name> <address> [--provider NAME] [--role ROLE]
infra_tools.py network import-proxmox <profile> [--host NAME] [--tag TAG]
infra_tools.py network import-proxmox-guests <profile> [--host NAME] [--tag TAG]
infra_tools.py network plan-proxmox <profile> [--proxmox] [--json]
```

`plan-proxmox` is read-only and requires at least one management source and
one control-plane address before it will produce a non-error plan.

### Proxmox Management

```bash
infra_tools.py proxmox add <name> <address> [--user USER] [--key PATH]
infra_tools.py proxmox probe <host>
infra_tools.py proxmox probe-cluster <address> [--user USER] [--key PATH] [--tag TAG]
infra_tools.py proxmox rolling-update <target> [<target> ...] [--dry-run] [--reboot-timeout SECONDS]
infra_tools.py proxmox ls <host>
infra_tools.py proxmox status <host> <vmid>
infra_tools.py proxmox start <host> <vmid>
infra_tools.py proxmox stop <host> <vmid> [--force]
infra_tools.py proxmox destroy <host> <vmid> [-y] [--force]
infra_tools.py proxmox health <host> <vmid> [--no-ssh]
infra_tools.py proxmox config <host> <vmid> [--pending]
infra_tools.py proxmox reconfigure <host> <vmid> --set KEY=VALUE [--set ...]
infra_tools.py proxmox modify <host> <vmid> [--cores N] [--memory N[M|G]]
infra_tools.py proxmox resize-disk <host> <vmid> <volume> <size>
infra_tools.py proxmox notifications install-webhook <host> <url> [--send-test]
infra_tools.py proxmox notifications test-webhook <host>
infra_tools.py proxmox [shell]
```

`probe` caches bridge, gateway, DNS, and storage recommendations. `rolling-update`
uses saved setup commands and workspace credentials. Mutating subcommands accept
`--dry-run` where supported.

### Interactive Shell

`infra_tools.py shell` opens a REPL for saved configurations. The shell loads
`~/.infra_toolsrc` on startup and persists history at
`~/.local/share/infra_tools/shell_history`.

Useful shell commands:

- `list`, `info`, `cmd`, `deploy`, `rm`, `recall`, `reconstruct`
- `new` / `setup` for a guided saved-setup flow
- `workspace` to change the active workspace
- `proxmox` to enter the Proxmox sub-shell

### Sysadmin Shortcuts

See [`SYSADMIN.md`](./SYSADMIN.md) for the host shortcut commands (`mount`,
`health`, `ssh`, `push`, `pull`, `df`, `fan`, `svc`, `logs`, `upgrade`,
`reachable`, `key`).

## Testing And Bootstrap

```bash
python3 -m unittest discover -s tests
./run_tests.py --suite smoke
sudo python3 infra_tools.py self-setup --user "$USER"
uv tool install --upgrade argcomplete
python3 infra_tools.py completions
```

The full test matrix, live Proxmox categories, and bootstrap details remain in
the code and `README.md`; this page is intentionally the concise command index.
