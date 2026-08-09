# Command-Line Reference

Concise reference for the unified `infra_tools.py` CLI. The code help and
`lib/arg_parser.py` remain the source of truth; this doc keeps the command
surface and the non-obvious behaviors that are easy to forget. Examples use
the checkout script; substitute the installed `infra_tools` launcher when it
is on `PATH`.

Related pages:

- [`SYSADMIN.md`](./SYSADMIN.md) for remote host shortcuts
- [`NETWORKING.md`](./NETWORKING.md) for workspace network inventory
- [`CICD.md`](./CICD.md) for webhook CI/CD setup
- [`WORKSTATIONS.md`](./WORKSTATIONS.md) for desktop profiles and application choices
- [`MACHINE_TYPES.md`](./MACHINE_TYPES.md) for machine type behavior
- [`README.md`](./README.md) for the full documentation map

## Unified Entry Point

```bash
infra_tools.py setup <system_type> <host> [username] [options]
infra_tools.py patch <host> [username] [options]
infra_tools.py shares <host> [username] [options]
infra_tools.py recall <host> [username] [options]
infra_tools.py reconstruct [--compact]
infra_tools.py list [pattern] [--json]
infra_tools.py info [pattern] [--compact]
infra_tools.py cmd [pattern]
infra_tools.py rm <pattern>
infra_tools.py deploy <pattern> [--yes]
infra_tools.py credentials set <username> [password]
infra_tools.py credentials list
infra_tools.py credentials remove <username>
infra_tools.py completions [options]
infra_tools.py python-tools [options]
infra_tools.py bootstrap [options]
infra_tools.py self-setup [options]
infra_tools.py agent doctor
infra_tools.py maintenance github <audit|prune> [options]
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
| `--machine TYPE` | Machine type override; defaults to `auto` on the target |
| `--name NAME` | Friendly name for the configuration |
| `--tags TAG1,TAG2` | Comma-separated tags |
| `--image SOURCE` | VM qcow2 URL or Proxmox storage reference; used with `--machine vm` |
| `--steps STEP...` | Run an explicit space-separated step list with `custom_steps` |
| `--dry-run` | Simulate execution |
| `--auto-restart` / `--no-auto-restart` | Control normal automatic restarts |
| `--auto-restart-force-days N` | Force restart after N days of deferrals |
| `--auto-restart-grace N` | Warning period before an automatic restart |

### Common Setup Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable or disable XRDP |
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

Selecting a language runtime also installs its managed update timer. See
[`MAINTENANCE.md`](./MAINTENANCE.md) for schedules and update policy.

### Agent VM Flags

These flags prepare a Debian VM for agentic coding. They work with any setup
type; `workstation_dev` is recommended when the agent needs a desktop/browser,
and `server_dev` is the recommended terminal-only profile. `server_lite` omits
the standard firewall and generic CLI bundle, so use it only when that lighter
profile is intentional.

```bash
infra_tools.py setup server_dev 10.0.0.10 agentuser \
  --agent-suite terminal --copy-config \
  --repo https://github.com/user/my_codebase.git
```

| Flag | Description |
|------|-------------|
| `--gh` | Install GitHub CLI from GitHub's Debian apt repository |
| `--codex` | Install Codex CLI with [OpenAI's official installer](https://github.com/openai/codex#installation) |
| `--claude` | Install Claude Code with [Anthropic's native installer](https://code.claude.com/docs/en/installation) |
| `--opencode` | Install OpenCode with its [official installer](https://opencode.ai/docs/) |
| `--t3code` | Install the verified [official T3 Code](https://github.com/pingdotgg/t3code) x86_64 AppImage, command, and desktop entry |
| `--agent-suite terminal` | Install GitHub CLI, Codex CLI, Claude Code, OpenCode, and common coding utilities |
| `--agent-suite desktop` | Install the terminal suite plus optional T3 Code |
| `--agent-suite full` | Install the desktop suite plus Node, Python, and Go tooling |
| `--copy-config` | Stage selected local config for tools enabled by the same command |
| `--copy-keys` | Stage selected local credentials for tools enabled by the same command |
| `--repo GIT_URL` | Clone locally, upload with the setup bundle, cache privately on the target, and copy to `/home/USER/repos/NAME`; repeatable |

Codex CLI, Claude Code, OpenCode, and T3 Code are installed from their official
distribution channels. infra_tools does not install these tools with npm. Any
selected agent also installs a baseline containing build tools, CMake, Ninja,
Git LFS, ripgrep, fd, fzf, jq, bat, tmux, direnv, and ShellCheck.

Credential/config copy is intentionally tool-scoped:

- `--gh --copy-config` copies GitHub CLI config such as `config.yml`, aliases, and extensions; it does not copy `hosts.yml`.
- `--gh --copy-keys` copies GitHub CLI `hosts.yml` when present and runs `gh auth setup-git` for the setup user when auth validates.
- `--codex --copy-config` copies known non-secret entries from `~/.codex`: `config.toml`, `AGENTS.md`, `skills`, and `rules`.
- `--codex --copy-keys` copies `~/.codex/auth.json` when present.
- `--claude --copy-config` copies known non-secret entries from `~/.claude`: settings, instructions, commands, agents, skills, and plugins.
- `--claude --copy-keys` copies `~/.claude/.credentials.json` when present.
- `--opencode --copy-config` copies `~/.config/opencode`, including global agents, skills, commands, plugins, and config files.
- `--opencode --copy-keys` copies `~/.local/share/opencode/auth.json` when present.
- T3 Code receives only a command wrapper and desktop entry; infra_tools does not copy T3 Code credentials.

The root-only upload payload is removed after the selected config and credentials
are copied. Uploaded agent repositories are retained in a root-only target cache
so repeated setup work does not expose private source to unrelated local users;
the user-facing workspace is copied and owned by the setup user. Repository
clones on the orchestration host are isolated by complete git URL. Agent
repository URLs with embedded credentials are rejected. A requested repository
that cannot be cloned stops setup instead of producing a successful VM without
its workspace. Existing destinations on the VM are still skipped to avoid
overwriting agent work on long-lived disposable VMs.

On the configured VM, check the terminal suite without exposing credential
contents:

```bash
infra_tools agent doctor
infra_tools agent doctor --tool t3code
infra_tools agent doctor --tool codex --tool claude --json
```

The default doctor check requires GitHub CLI, Codex CLI, Claude Code, and
OpenCode. Missing credential files are reported as sign-in reminders but do not
make an otherwise installed tool unhealthy. GitHub CLI and the Debian utility
baseline receive normal APT updates. Codex CLI, Claude Code, and OpenCode do not
currently have infra_tools-managed update timers, and rerunning setup skips an
already available command. See the [agent-host maintenance audit](./plans/AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md)
for the planned versioned update and audit workflow.

The normal restart policy can force a reboot after seven days of active-session
deferrals. For a host running long unattended agent tasks, use both
`--no-auto-restart` and `--auto-restart-force-days 0` if automatic restarts must
be fully disabled, then manage pending security reboots explicitly.

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
- Direct setup defaults to `--machine auto`, which detects Debian bare metal,
  VMs, and Proxmox LXC containers on the target.
- Hosted Proxmox setup defaults to a VM because it is creating a new guest;
  use `--machine unprivileged` for an LXC.
- `--machine unprivileged` keeps an existing or intentional LXC path.

## Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy a repository to a domain |
| `--deploy-latest DOMAIN_OR_PATH GIT_URL` | Deploy while bypassing the release/dependency freshness policy |
| `--deployment-lite` | Use cached/pre-uploaded repository files only |
| `--deployment-full` | Pull fresh repositories and rebuild everything |
| `--full-deploy` | Always rebuild deployments even if unchanged |
| `--reset-migrations` | Rebuild a Rails database schema when migration history was squashed or reset |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email EMAIL` | Email for SSL registration |
| `--cloudflare` | Configure Cloudflare Tunnel |
| `--api-subdomain` | Deploy Rails API to `api.domain.com` |

Repos can also ship `infra.json` manifests for multi-component deploys; see
[Deployments and manifests](./DEPLOYMENTS.md) for the schema and examples.

## CI/CD and Build / App Servers

| Flag | Description |
|------|-------------|
| `--build-server` | Configure a build server that deploys to app servers |
| `--app-server` | Configure an app server to receive deployments |
| `--deploy-target HOST` | Target app server for deployments |
| `--cicd` | Install the signed GitHub webhook receiver and isolated executor |

See [`CICD.md`](./CICD.md) for webhook configuration, service units, and
deployment-boundary behavior.

## Antistatic

`--antistatic-server` and `--antistatic-db` deploy the release binaries
maintained in code. Hostname-based specs are reverse-proxied through nginx;
hostless specs such as `:8080` or `:8081` listen directly on the target port.

| Flag | Description |
|------|-------------|
| `--antistatic-server [DOMAIN][:PORT]` | Deploy the lobby server |
| `--antistatic-admin USERNAME` | Enable HTTPS-only report administration using the matching workspace credential |
| `--no-antistatic-admin` | Disable administration and remove its remote credential file |
| `--antistatic-db [DOMAIN][:PORT]` | Deploy antistatic-db |

The lobby server stores bounded report collections under
`/var/lib/antistatic`, sends a local `/health` probe after each service start,
and exposes STUN directly on UDP 3478. Hostname deployments redirect ordinary
HTTP traffic to HTTPS; `--cloudflare` instead marks tunnel traffic secure at
the private nginx-to-server boundary.

Admin access requires a hostname deployment and either `--ssl` or
`--cloudflare`. Store its password separately, then reference the username.
See [Antistatic services](./ANTISTATIC.md) for the complete workflow and
credential-storage behavior.

## Gogs

See [Gogs Git service](./GOGS.md) for hostname and hostless modes, initial
credentials, Git-over-SSH, data layout, and update recovery.

Deploy a minimal self-hosted Git service with an optional hostname, port, and
data directory:

```bash
infra_tools.py setup server_web 192.168.1.10 \
  --gogs git.example.com:3000 /var/lib/gogs \
  --ssl --ssl-email admin@example.com
```

Use `--gogs :3000` for hostless direct mode. Gogs updates are validated before
activation and can roll back to the previous release if post-update commands
or restart checks fail.

## Storage And Data Movement

| Flag | Description |
|------|-------------|
| `--samba` | Install and harden Samba for authenticated SMB3 file sharing |
| `--share TYPE NAME PATH USERS` | Configure one Samba directory share |
| `--credential USERNAME PASSWORD` | Define a password for username-only share entries |
| `--smbclient` | Install SMB/CIFS client |
| `--mount-smb MOUNTPOINT IP CREDENTIALS SHARE SUBDIR` | Mount an SMB share persistently; `SUBDIR` may be `/` |
| `--sync SOURCE DEST INTERVAL` | Configure rsync sync |
| `--scrub DIR DBPATH REDUNDANCY FREQ` | Configure par2 integrity checking |
| `--notify TYPE TARGET` | Configure notifications |

Samba shares are authenticated and hardened; `TYPE` is `read` or `write`, and
`PATH` is one absolute directory. See [Samba Shares](./SAMBA_SHARES.md) for
credentials, access control, fast updates, removals, and SMB client mounts.
See [Storage operations](./STORAGE_OPERATIONS.md) for sync, parity, schedules,
mount checks, and logs, and [Notifications](./NOTIFICATIONS.md) for delivery
targets and failure behavior.

## Maintenance and Utilities

### GitHub Maintenance

```bash
infra_tools.py maintenance github audit --root /home/loren/repos
infra_tools.py maintenance github prune --root /home/loren/repos --yes
infra_tools.py maintenance github prune --root /home/loren/repos --delete-caches --yes
```

Defaults: keep 2 releases, delete expired artifacts, prune caches only when
`--delete-caches` is set, and treat caches as stale after 90 days.

Use `--dry-run` to inspect planned deletions. The command discovers repositories
from the current directory by default, or from repeatable `--root` paths, and
requires the local `gh` CLI to be authenticated.

### Recurring Host Maintenance

Security monitoring, package updates, ecosystem updates, restart checks, and
cleanup are installed as systemd services and timers during setup. Inspect them
with:

```bash
sudo systemctl list-timers --all '*auto-*' '*security-monitor*' '*cleanup-*'
sudo journalctl -u cleanup-maintenance.service -n 100 --no-pager
```

See [`MAINTENANCE.md`](./MAINTENANCE.md) for schedules and policy controls.

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
infra_tools.py proxmox audit <host> [<host> ...] [--json]
infra_tools.py proxmox rolling-update <target> [<target> ...] [--dry-run] [--reboot-timeout SECONDS]
infra_tools.py proxmox top <host> [<host> ...]
infra_tools.py proxmox plan place [options]
infra_tools.py proxmox plan rebalance [options]
infra_tools.py proxmox ls <host>
infra_tools.py proxmox status <host> <vmid>
infra_tools.py proxmox start <host> <vmid>
infra_tools.py proxmox pause <host> <vmid>  # alias: suspend
infra_tools.py proxmox resume <host> <vmid>
infra_tools.py proxmox stop <host> <vmid> [--force]
infra_tools.py proxmox destroy <host> <vmid> [-y] [--force]
infra_tools.py proxmox health <host> <vmid> [--no-ssh]
infra_tools.py proxmox config <host> <vmid> [--pending]
infra_tools.py proxmox reconfigure <host> <vmid> --set KEY=VALUE [--set ...]
infra_tools.py proxmox modify <host> <vmid> [--cores N] [--memory N[M|G]]
infra_tools.py proxmox resize-disk <host> <vmid> <volume> <size>
infra_tools.py proxmox backups <host> <vmid>
infra_tools.py proxmox backup <host> <vmid> [--storage POOL] [--mode MODE] [--compress FORMAT]
infra_tools.py proxmox migrate <host> <vmid> <target> [--online] [--with-local-disks]
infra_tools.py proxmox clean-disks <host> [--delete] [--yes] [--dry-run]
infra_tools.py proxmox unlock <host> <vmid> [--dry-run]
infra_tools.py proxmox notifications install-webhook <host> <url> [--send-test]
infra_tools.py proxmox notifications test-webhook <host>
infra_tools.py proxmox [shell]
```

`probe` caches bridge, gateway, DNS, and storage recommendations. `audit` is
read-only and checks core Proxmox services, cluster quorum, active tasks,
configured storage, root free space, guest locks, running guests, and the reboot
marker. It exits nonzero when the host is not healthy and supports stable JSON
output for automation.

`rolling-update` uses saved setup commands and workspace credentials. It audits
all targets before making changes, audits each node again after its update and
reboot, and stops before an automatic reboot if that node still has running or
locked guests. Mutating subcommands accept `--dry-run` where supported; a rolling
update dry run still performs the read-only preflight audits.

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
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sh -s -- \
  --setup server_dev localhost "$USER" \
  --machine hardware \
  --agent-suite terminal
sudo python3 infra_tools.py self-setup --user "$USER"
uv tool install --upgrade argcomplete
infra_tools completions
```

For a full Debian bootstrap or an immediate setup handoff:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER"

curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --setup server_proxmox 10.0.0.10 root --key "$HOME/.ssh/proxmox_ed25519"
```

Everything after `--setup` is passed to `infra_tools setup`. The full test
matrix and detailed bootstrap behavior are covered by
[`OPERATIONS.md`](./OPERATIONS.md) and [`INSTALLATION.md`](./INSTALLATION.md);
this page is intentionally the concise command index.
For a local setup, the installer defaults an omitted setup username to the
selected install user and uses `sudo` only for the privileged setup phase.
