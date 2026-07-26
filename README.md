
# infra_tools

Automated setup scripts for remote Linux systems (Debian).

> **AI Agents:** See [`.github/ai-agents/`](.github/ai-agents/) for development guidance.
>
> **Machine Types:** See [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for environment-specific configuration.

## Quick Start

```bash
# Install for the current user (required command-line prerequisites must exist).
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh

python3 infra_tools.py setup server_web example.com admin --ruby --node --deploy example.com https://github.com/user/repo.git
python3 infra_tools.py setup server_dev 10.0.0.10 agentuser --agent-suite terminal --copy-config --repo https://github.com/user/my_codebase.git
python3 infra_tools.py setup workstation_desktop 192.168.1.100 admin --desktop i3 --browser firefox
python3 infra_tools.py patch example.com admin --ssl --deploy api.example.com https://github.com/user/api.git
python3 infra_tools.py credentials set guest s3cret
```

## What It Does

- **Servers**: Security hardening, Nginx/SSL, Ruby/Node/Go, app deployment, game lobby server
- **Workstations**: Desktop environments (XFCE, i3, LXQt), RDP, browsers, audio
- **Storage**: Samba shares, rsync sync, par2 integrity verification
- **Security**: Firewall, SSH hardening, fail2ban, hardened OS auto-updates, weekly cleanup maintenance, journald size limits
- **Deployments**: Single-service deploys plus repo-defined `infra.json` manifests for multi-component apps
- **Network inventory**: workspace-backed network profiles and read-only Proxmox control-plane firewall planning — see [docs/NETWORKING.md](./docs/NETWORKING.md)
- **Sysadmin shortcuts**: mount, health, ssh, push/pull, df, fan, svc, logs, upgrade, reachable — see [docs/SYSADMIN.md](./docs/SYSADMIN.md)

Background maintenance includes a `cleanup-maintenance` systemd timer that reclaims temporary files,
stale infra_tools setup/deploy artifacts, unused APT packages, old package-manager caches, and oversized journals.
Infra tools also installs a journald drop-in at `/etc/systemd/journald.conf.d/infra-tools.conf` to cap
persistent and runtime journal usage at `100M`.

Automatic update policy is intentionally conservative for language ecosystems. APT updates still run
automatically, but the updater refuses automated package removals. Node.js, Ruby, and uv timers no longer
auto-upgrade global npm packages, gems, or uv-managed tools unless `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1`
is set for the service. Node.js defaults to the LTS track; if a non-LTS/latest Node.js track is already
installed, the Node updater treats that as an explicit opt-in and keeps that track current too.
Dependency-resolving npm and uv installs default to `INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS=7` so very new
package releases are avoided where the package manager supports a freshness cutoff.

## CLI Entry Points

| Script | Description |
|--------|-------------|
| `infra_tools.py` | **Unified entry point** - Use `setup`, `patch`, `list`, `info`, `cmd`, `rm`, `deploy`, `recall`, `reconstruct`, `completions`, `python-tools`, `bootstrap`, `agent`, `credentials`, `network`, `proxmox`, `shell`, or any [sysadmin shortcut](./docs/SYSADMIN.md) |

Use `infra_tools.py` for all system setup, saved-configuration management, patching, recall, reconstruction,
local Python tooling, and shell-completion setup.

See [Command-Line Reference](./docs/COMMAND_LINE.md) for setup/patch flags, [Network Inventory](./docs/NETWORKING.md) for the `network` workflow, and [Sysadmin Commands](./docs/SYSADMIN.md) for day-to-day shortcuts.

## Common Examples

### Web Server with Deployment
```bash
python3 infra_tools.py setup server_web web.com \
  --ruby --node \
  --ssl --ssl-email admin@web.com \
  --deploy web.com https://github.com/user/repo.git
```

### Agent VM Workspace
```bash
python3 infra_tools.py setup server_dev 10.0.0.10 agentuser \
  --agent-suite terminal \
  --copy-config \
  --repo https://github.com/user/my_codebase.git
```

This installs GitHub CLI, Codex CLI, Claude Code, OpenCode, and a common Debian
coding-tool baseline. It uploads selected non-secret local config and copies
each uploaded repo to `/home/agentuser/repos`. Add `--copy-keys` only for a VM
trusted with your existing credentials. Existing repo destinations are skipped
to avoid overwriting in-progress agent work. See
[`docs/COMMAND_LINE.md`](./docs/COMMAND_LINE.md) for presets and individual
tool flags.

### Remote Desktop Workstation
```bash
python3 infra_tools.py setup workstation_desktop 192.168.1.100 admin --desktop i3 --browser firefox
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

### Quick Setup: Proxmox Host to Agentic Coding VM

This is the primary end-to-end path: start with an existing Proxmox VE host at
`10.0.0.10`, inspect it with infra_tools, then create a Debian desktop VM at
`10.0.0.50`. Run these commands from a trusted Linux orchestration machine, not
from inside the future VM.

Start from a current checkout. The Proxmox host itself does not need an existing
checkout: `setup server_proxmox` uploads this checkout to `/opt/infra_tools`,
replacing an older uploaded copy if one exists.

```bash
git clone https://github.com/bluehexagons/infra_tools.git
cd infra_tools
git pull --ff-only

# Optional: install the infra_tools launcher and shell completion locally.
sudo python3 infra_tools.py self-setup --user "$USER"
```

The examples use `~/.ssh/proxmox_ed25519`; its public key must exist alongside
it as `~/.ssh/proxmox_ed25519.pub`, and root on the Proxmox host must accept it.

```bash
# 1. Upload the current infra_tools source and apply the Proxmox host setup.
python3 infra_tools.py setup server_proxmox 10.0.0.10 root \
  --key ~/.ssh/proxmox_ed25519 \
  --name pve1

# 2. Register and probe the host, then pull a live resource/guest summary.
python3 infra_tools.py proxmox add pve1 10.0.0.10 \
  --user root \
  --key ~/.ssh/proxmox_ed25519
python3 infra_tools.py proxmox probe pve1
python3 infra_tools.py proxmox top pve1
python3 infra_tools.py proxmox ls pve1

# 3. Create a Debian VM and configure XFCE, RDP, Firefox, and coding tools.
#    10.0.0.50 must be unused and reachable on the Proxmox bridge subnet.
python3 infra_tools.py setup workstation_dev 10.0.0.50 agent \
  --hosted pve1 \
  --base debian \
  --name agent-dev-01 \
  --cores 4 \
  --memory 8G \
  --storage root 40G \
  --desktop xfce \
  --rdp \
  --browser firefox \
  --agent-suite terminal \
  --copy-config \
  --repo https://github.com/user/my_codebase.git \
  --node --go --python

# 4. Find the assigned VMID, inspect the VM, and check guest connectivity.
python3 infra_tools.py proxmox ls pve1
python3 infra_tools.py proxmox config pve1 100
python3 infra_tools.py proxmox health pve1 100
```

When a registered host has an SSH key, hosted setup reuses it for cloud-init and
guest setup. Pass `--key ~/.ssh/agent_vm_ed25519` in step 3 to use a separate VM
key instead. The recommended command leaves authentication for first launch.
Add `--copy-keys` to copy credentials for the selected tools only when the VM is
trusted. Add `--t3code` for the optional T3 Code desktop AppImage on x86_64.

The agent CLIs use their official user-scoped installers—not npm—and no installer
is used to sign in automatically. On the VM, verify the tools and authenticate
any account that was not copied:

```bash
infra_tools agent doctor
codex
claude
opencode
gh auth login
```

T3 Code support is deliberately minimal: infra_tools verifies the checksum
published with the latest official x86_64 AppImage, installs it under
`~/.local/share/t3code`, and adds `t3code` plus an application-menu entry. Run
`infra_tools agent doctor --tool t3code` to check it without launching the GUI.

SSH key access works immediately. Before the first RDP login, set a desktop
password interactively so it is not exposed in shell history:

```bash
ssh -t agent@10.0.0.50 'sudo passwd agent'
```

Then connect over RDP to `10.0.0.50:3389` as `agent`. Replace `100` below with
the VMID shown by `proxmox ls`:

```bash
python3 infra_tools.py proxmox status pve1 100
python3 infra_tools.py proxmox pause pve1 100       # freeze RAM/CPU state
python3 infra_tools.py proxmox resume pve1 100
python3 infra_tools.py proxmox stop pve1 100        # graceful shutdown
python3 infra_tools.py proxmox start pve1 100
python3 infra_tools.py proxmox snapshot pve1 100 before_upgrade
python3 infra_tools.py proxmox destroy pve1 100     # permanent; asks for confirmation
```

To reapply the saved workstation configuration later, run
`python3 infra_tools.py deploy agent-dev-01`. For a multi-node cluster, use
`proxmox probe-cluster` from one seed node instead of registering every node
manually.

#### Alternate: force the workstation onto an LXC

Use `--machine unprivileged` only when you explicitly want a lighter-weight LXC.
This keeps basic workstation support, but advanced VM-oriented polish such as
full kernel/firewall behavior and the best desktop experience should be expected
on the default VM path — see [`docs/MACHINE_TYPES.md`](docs/MACHINE_TYPES.md) for
the full capability matrix.

Replace step 3 with the LXC variant below. The Proxmox host setup (step 1) and
registration (step 2) are unchanged.

```bash
# 3b. Provision the workstation as an unprivileged Debian LXC instead.
#     LXC still works for the basic path, but VM is now the primary hosted default.
infra_tools setup workstation_dev 10.0.0.50 devuser \
  --machine unprivileged \
  --hosted pve1 \
  --base debian \
  --name dev-01-lxc \
  --cores 4 \
  --memory 8G \
  --storage root 40G \
  --storage template \
  --desktop i3 \
  --rdp \
  --browser firefox \
  --ruby --node --go --python \
  --office
```

`infra_tools proxmox` subcommands work the same way for VMs as for LXCs — the
vmid returned by step 3b can be used directly with `proxmox health`, `modify`,
`stop`, `destroy`, etc.

### Hosted Proxmox VM or LXC
```bash
# Create a VM on Proxmox, then run the normal web-server setup against it
python3 infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted pve1 \
  --memory 4G \
  --storage root 32G \
  --cores 2 \
  --base debian \
  --name web-01-vm \
  --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

To stay on the LXC path instead, add `--machine unprivileged`, use a root
storage spec, and include template storage:

```bash
python3 infra_tools.py setup server_web 10.0.0.50 admin \
  --machine unprivileged \
  --hosted pve1 \
  --memory 4G --cores 2 \
  --storage root 20G \
  --storage template \
  --base debian \
  --name web-01-lxc \
  --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

`--storage` is repeatable. `root` may be given as `--storage root POOL AMOUNT` or the shorthand
`--storage root AMOUNT`, which reuses a saved Proxmox host default and otherwise falls back to
Proxmox auto-detection. LXC `template` storage is optional and may be given as `--storage template`
to reuse the saved/default template pool.

Upgrade note: if you are rerunning a copied main-era single-system command for
an existing hosted LXC `server_web`, `server_dev`, `workstation_desktop`,
`workstation_dev`, or `pc_dev`, add `--machine unprivileged`. Saved `deploy` and `patch` workflows
preserve the cached machine type when `--machine` is omitted.

### Managing Proxmox Guests

Register Proxmox hosts and manage their VMs or LXC compatibility guests from a workspace registry. The same
subcommands work for both — VMIDs are unique per node regardless of guest type. Run `proxmox` with no
subcommand to enter an interactive shell, or use subcommands directly:

```bash
# Register and inspect hosts
python3 infra_tools.py proxmox add pve1 10.0.0.10 --user root --key ~/.ssh/proxmox_ed25519
python3 infra_tools.py proxmox probe pve1
python3 infra_tools.py proxmox probe-cluster 10.0.0.10 --key ~/.ssh/proxmox_ed25519 --tag prod
python3 infra_tools.py proxmox rolling-update pve1 pve2 pve3
python3 infra_tools.py proxmox hosts
python3 infra_tools.py proxmox ls pve1

# Guest lifecycle
python3 infra_tools.py proxmox start pve1 101
python3 infra_tools.py proxmox pause pve1 101
python3 infra_tools.py proxmox resume pve1 101
python3 infra_tools.py proxmox stop pve1 101
python3 infra_tools.py proxmox health pve1 101
python3 infra_tools.py proxmox destroy pve1 101 -y

# Guest configuration and resource changes
python3 infra_tools.py proxmox config pve1 101
python3 infra_tools.py proxmox modify pve1 101 --cores 4 --memory 8G
python3 infra_tools.py proxmox reconfigure pve1 101 --set hostname=newbox
python3 infra_tools.py proxmox resize-disk pve1 101 rootfs 40G

# Snapshots
python3 infra_tools.py proxmox snapshots pve1 101
python3 infra_tools.py proxmox snapshot pve1 101 pre-upgrade --description "before kernel update"
python3 infra_tools.py proxmox rollback pve1 101 pre-upgrade
python3 infra_tools.py proxmox delsnapshot pve1 101 pre-upgrade

# Native Proxmox webhook notifications
python3 infra_tools.py proxmox notifications install-webhook pve1 https://notify.example/hook --send-test

# Interactive Proxmox shell
python3 infra_tools.py proxmox shell
```

The registry is stored at `<workspace>/proxmox_hosts.json` (mode `0600`).
`proxmox probe` caches bridge, gateway, DNS, and storage-pool recommendations so later `setup --hosted`
runs can target a registered host by name and omit manual pool names.
`proxmox probe-cluster` starts from one reachable node IP/hostname, discovers every cluster member from
Proxmox's configured node names, and seeds the host registry for the whole cluster in one step; `--tag`
values are applied to newly discovered nodes.
`proxmox rolling-update` reuses saved setup commands plus workspace credentials, validates every target
before touching any node, applies patches in the order given, and waits for any required reboot before
continuing.
Proxmox notifications use the native Proxmox webhook endpoint and matcher via `pvesh` — no local hook script
is installed. `modify` and `reconfigure` changes that affect a running guest may require a restart.

### Network Inventory and Proxmox Firewall Planning

The `network` command keeps a workspace-scoped inventory of management sources,
control-plane addresses, guest networks, and tagged hosts, then renders a
read-only Proxmox control-plane lockdown plan for review.

```bash
python3 infra_tools.py network init homelab --management 192.168.1.0/24
python3 infra_tools.py network import-proxmox homelab --tag prod
python3 infra_tools.py network import-proxmox-guests homelab --tag prod
python3 infra_tools.py network plan-proxmox homelab
python3 infra_tools.py network plan-proxmox homelab --proxmox
```

Profiles are stored in `<workspace>/network_inventory.json` (mode `0600`).
The current planner is intentionally read-only and exits non-zero when required
safety inputs such as management sources or control-plane addresses are missing.
See [docs/NETWORKING.md](./docs/NETWORKING.md) for the full command reference.

### Interactive Shell

The `shell` subcommand opens an interactive REPL for configuration management:

```bash
python3 infra_tools.py shell
```

Inside the shell:
- `list [pattern] [--json]` / `info [pattern] [--compact]` — browse saved configurations
- `new` / `setup` — guided flow for creating a new saved setup from common prompts
- `deploy <pattern> [--yes]` — redeploy saved configurations
- `rm <pattern> [--yes]` — remove configurations
- `recall <host> [user]` — fetch a setup command from a remote host
- `workspace [path]` — show or switch the active workspace
- `proxmox` — drop into the Proxmox sub-shell

The guided `new` flow can optionally start from an existing saved setup, then
optionally attach the new system to a registered Proxmox host before prompting
for common fields such as name, IP address, machine type, system type, and a
small set of common workstation/web-server options.

The shell loads `~/.infra_toolsrc` on startup — put any commands you want to run at the start of each session
(e.g., `workspace /path/to/project`) in that file, one per line.
Command history is persisted at `~/.local/share/infra_tools/shell_history`.

### Saved Configuration Output

The `list` and `info` commands support machine-readable output for scripting:

```bash
# JSON array of all saved configurations
python3 infra_tools.py list --json

# One-line summary per configuration
python3 infra_tools.py info --compact
```

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

For the live Proxmox category, the primary path is a VM run (`PROXMOX_TEST_GUEST_TYPE=vm`,
`PROXMOX_TEST_IP=...`). Use `PROXMOX_TEST_GUEST_TYPE=lxc` with `PROXMOX_TEST_TEMPLATE=...`
for the LXC compatibility path.

Each category also has a matching env var (e.g. `INFRA_TOOLS_RUN_LIVE_PROXMOX=1`),
or set `INFRA_TOOLS_RUN_EXPENSIVE=1` to enable everything. See
[`tests/expensive_support.py`](tests/expensive_support.py) for details and
[`tests/test_proxmox_live.py`](tests/test_proxmox_live.py) for the env vars
needed to point the live Proxmox test at a real host.

### Real-System Smoke Test

Before broad rollout, the highest-value manual validation is a short Proxmox
smoke pass on one VM-first flow plus one LXC compatibility flow:

```bash
# 0. Register the Proxmox host and cache its defaults (skip if already done)
infra_tools.py proxmox add pve1 10.0.0.10 --user root --key ~/.ssh/proxmox_ed25519
infra_tools.py proxmox probe pve1

# 1. VM-first hosted setup (primary path)
infra_tools.py setup workstation_dev 10.0.0.50 devuser \
  --hosted pve1 \
  --memory 8G \
  --storage root 40G \
  --cores 4 \
  --name dev-01-vm \
  --rdp

# 2. Guest management sanity checks against the created VM
infra_tools.py proxmox ls pve1
infra_tools.py proxmox health pve1 <vmid>
infra_tools.py proxmox config pve1 <vmid>
infra_tools.py proxmox snapshot pve1 <vmid> pre-modify
infra_tools.py proxmox modify pve1 <vmid> --cores 6 --memory 12G
infra_tools.py proxmox stop pve1 <vmid>
infra_tools.py proxmox start pve1 <vmid>

# 3. LXC compatibility check (basic support path)
infra_tools.py setup server_lite 10.0.0.60 appuser \
  --machine unprivileged \
  --hosted pve1 \
  --memory 2G \
  --storage root 10G \
  --storage template
```

For the VM path, verify SSH access and, if enabled, RDP login after first boot.
For the LXC path, basic provisioning and guest-management behavior are the main
compatibility target; advanced desktop polish is intentionally VM-first.

Use `--credential USERNAME PASSWORD` to define share passwords once, then reference those users by username
in `--share` or `--mount-smb`. The `USERS` field accepts a comma-separated list of `username` or `username:password`
entries, and each bare username must have a matching saved credential. Use `infra_tools.py credentials set USERNAME
PASSWORD` to manage the shared workspace store directly.

### Sysadmin Shortcuts

Day-to-day commands that work against any saved (or ad-hoc) host. Credentials are
inherited from the saved config automatically. See [docs/SYSADMIN.md](./docs/SYSADMIN.md)
for the full reference.

```bash
# Mount a remote directory (sshfs)
infra_tools mount myserver:/var/log /mnt/logs
infra_tools umount /mnt/logs

# Health dump: uptime, memory, disk, failed units, pending upgrades
infra_tools health myserver

# Open an SSH session with saved credentials
infra_tools ssh myserver
infra_tools ssh myserver -- journalctl -f

# File transfer (rsync)
infra_tools push ./dist myserver:/var/www/app
infra_tools pull myserver:/var/log ./logs

# Disk usage across multiple hosts (sorted by %, >85% flagged)
infra_tools df web1 web2 db1

# Run a command on multiple hosts in parallel
infra_tools fan web1 web2 db1 -- uptime

# Manage systemd services
infra_tools svc myserver nginx
infra_tools svc myserver nginx restart
infra_tools logs myserver nginx -f

# Upgrade packages (parallel, reports reboot-required)
infra_tools upgrade web1 web2

# Check which saved hosts are reachable
infra_tools reachable
```

### Game Lobby Server (Antistatic)
```bash
# Deploy the antistatic lobby server behind nginx (reruns upgrade to the latest GitHub release)
python3 infra_tools.py setup server_lite 192.168.1.10 --antistatic-server lobby.example.com

# With custom internal port (default: 8080)
python3 infra_tools.py setup server_web 192.168.1.10 --antistatic-server lobby.example.com:9090 --ssl

# Hostless direct port, no nginx virtual host
python3 infra_tools.py setup server_lite 192.168.1.10 --antistatic-server :8080
# If UFW is active, hostless mode also opens the selected direct TCP port.

# The lobby server binary is fetched from github.com/bluehexagons/antistatic-server/releases
# Runs as a locked-down systemd service with automatic restart on failure

# Deploy antistatic-db behind nginx, or use :8081 for direct hostless mode
python3 infra_tools.py setup server_web 192.168.1.10 --antistatic-db db.example.com --ssl
```

Workspace state now lives under `~/.config/infra_tools` by default. Use `--workspace /path/to/workspace` to isolate
saved setups, credentials, and history for a project or test environment.

## Requirements

- Python 3.10+
- SSH root access to target system
- Target OS: Debian

### Local Orchestration Host Bootstrap

The hosted installer downloads a GitHub source archive, installs prerequisites,
creates system and user launchers, and configures Python tooling and completion:

```bash
# Current-user install when prerequisites already exist.
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh

# Full Debian bootstrap, including system packages.
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER"

# wget works too.
wget -qO- https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
```

The installer can immediately hand off to any normal `setup` command. Arguments
after `--setup` are forwarded unchanged:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --setup server_proxmox 10.0.0.10 root \
  --key "$HOME/.ssh/proxmox_ed25519" \
  --name pve1
```

Run the one-liner only after reviewing [`install.sh`](./install.sh), particularly
on privileged hosts. Re-running it updates the source and keeps the previous
source directory as a timestamped backup. A bootstrap failure automatically
restores the previous source. The optional setup runs as the selected user so
workspace state and SSH keys resolve to that user's home.

From an existing checkout, the equivalent bootstrap command is:

```bash
sudo python3 infra_tools.py self-setup --user "$USER"
```

`self-setup` is an alias for `bootstrap`. After it runs, you can invoke the tool from any directory as
`infra_tools <command> ...` instead of `python3 /path/to/infra_tools.py <command> ...`. The launcher is
installed to `/usr/local/bin/infra_tools` for system-wide use and `~/.local/bin/infra_tools` for the
target user. Shell completion is registered for both `infra_tools` and `infra_tools.py`.

Bootstrap also installs `/etc/tmpfiles.d/infra_tools.conf`, which registers known infra_tools temp
prefixes with `systemd-tmpfiles-clean` as an additional safety net alongside the cleanup-maintenance timer.

## Shell Completion

The unified CLI supports tab completion for bash, zsh, and fish.

```bash
uv tool install --upgrade argcomplete
python3 infra_tools.py completions
```

See [docs/SHELL_COMPLETION.md](docs/SHELL_COMPLETION.md) for detailed setup.

## License

Apache License 2.0
