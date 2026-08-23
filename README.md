# infra-tools

Automated setup and operations for Debian control planes, servers, workstations,
and Proxmox guests. infra-tools applies repeatable, machine-aware configuration
over SSH, stores redacted setup state in a workspace, and provides targeted
operations for hosts that are already configured.

The documentation in this checkout describes the upcoming stable `v2.0.0`
release. Until that tag is published, the installer’s `dev` channel tracks
`main`; use `stable` when you need the latest published release.

## Start here

The supported workflow starts with the installer. It keeps the repository
locally, installs the managed `infra-tools` launcher, and lets you switch
channels or upgrade later. Choose the path that matches the machine.

The installer needs either `wget` or `curl` to fetch itself. The examples use
`wget`, which is commonly available on minimal Debian systems. If only `curl`
is installed, replace the download command with
`curl --fail --location --connect-timeout 15 --max-time 120 -o "$HOME/.infra_tools-install.sh" URL`.
If neither command is available, install one first with `sudo apt-get update && sudo apt-get install -y wget ca-certificates`.

The download commands intentionally leave connection diagnostics visible and
bound retries so a DNS or network failure is not mistaken for a stalled
installer. Every example downloads to a user-owned file before running the
installer, keeping password prompts and output connected to the terminal. Run
each command in order, confirm the download succeeds, and remove the file when
the installer finishes.

Install the launcher and choose a setup later:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sh "$HOME/.infra_tools-install.sh"
rm -f "$HOME/.infra_tools-install.sh"
```

Set up a minimal Debian control plane immediately:

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --local-setup control_plane \
  --agent-tool gh --agent-tool codex --agent-tool claude --agent-tool opencode
rm -f "$HOME/.infra_tools-install.sh"
```

Set up a standard Debian GNOME desktop as a graphical control plane. This keeps
GNOME for local logins, uses XFCE for RDP, and installs the agent-workstation
defaults (GitHub CLI and Codex CLI):

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sudo sh "$HOME/.infra_tools-install.sh" --user "$USER" --local-setup agent_workstation \
  --control-plane --desktop xfce --rdp --rdp-existing-password
rm -f "$HOME/.infra_tools-install.sh"
```

After installation, use `infra-tools setup ...` for remote hosts and
`infra-tools upgrade` to update the selected channel. See the concise
[installation guide](docs/INSTALLATION.md) for prerequisites, verification,
channels, credentials, RDP, and recovery. The [documentation index](docs/README.md)
organizes detailed feature and operations guides.

Contributors should also read the [AI agent guidance](.github/ai-agents/README.md)
before changing the project.

## Supported targets

infra-tools officially supports Debian on:

- bare-metal systems;
- virtual machines, including Proxmox-provisioned VMs; and
- unprivileged Debian LXC containers on Proxmox.

The installer and setup preflight also recognize Ubuntu and Linux Mint as
best-effort Debian-compatible environments. Debian remains the only officially
supported distribution.

The normal direct setup path uses `--machine auto`. Hosted Proxmox setup
defaults to a VM; select `--machine unprivileged` for the supported LXC path.
See [Machine types](docs/MACHINE_TYPES.md) for capability and compatibility
details.

## Capabilities

| Area | Summary | Detailed guide |
| --- | --- | --- |
| Setup and CLI | Unified `setup`, `patch`, `shares`, saved-host operations, and utility commands | [Command-line reference](docs/COMMAND_LINE.md) |
| Installation | User/system bootstrap, orchestration host prerequisites, and completion | [Installation](docs/INSTALLATION.md) |
| Control planes | Local VM/container administration tools, SSH/rsync, diagnostics, and optional coding agents | [Installation](docs/INSTALLATION.md), [Workstations](docs/WORKSTATIONS.md), [Credentials](docs/CREDENTIALS.md), [Browser automation](docs/BROWSER_AUTOMATION.md) |
| Servers | Security hardening, Nginx/SSL, Cloudflare tunnels, language runtimes, deployments, Gogs, and Antistatic | [CLI reference](docs/COMMAND_LINE.md), [Gogs](docs/GOGS.md), [Cloudflare tunnels](docs/CLOUDFLARE.md), [Antistatic](docs/ANTISTATIC.md) |
| Workstations | XFCE, i3, LXQt, RDP, browsers, and desktop tooling | [Workstations](docs/WORKSTATIONS.md), [XRDP](docs/XRDP.md), [CLI reference](docs/COMMAND_LINE.md) |
| Storage | Authenticated Samba shares, SMB mounts, rsync sync, par2 verification, and recurring operations | [Samba shares](docs/SAMBA_SHARES.md), [Storage operations](docs/STORAGE_OPERATIONS.md) |
| Deployments | Single-service deployments and `infra.json` multi-component manifests | [Deployments](docs/DEPLOYMENTS.md), [Deployment safety](docs/DEPLOYMENT_SAFETY.md), [CI/CD](docs/CICD.md) |
| Proxmox | Host discovery, VM/LXC provisioning, lifecycle, resource stats, boot ordering, snapshots, and rolling updates | [Proxmox workflows](docs/PROXMOX.md) |
| Networking | Static Debian host addressing, workspace-backed inventory, and read-only Proxmox firewall planning | [Networking](docs/NETWORKING.md) |
| Sysadmin | SSH, transfers, health, services, logs, upgrades, and reachability | [Sysadmin shortcuts](docs/SYSADMIN.md) |

## Operating policies

### Safety and state

Setup arguments are saved without passwords, reconstructed commands redact
secrets, and workspace credential files use restrictive permissions. Deployments
keep persistent application state outside release directories and create
verified backups where required. Read [Deployment safety](docs/DEPLOYMENT_SAFETY.md)
for rollback and recovery behavior.

### Machine awareness

Steps detect the target machine type and skip capabilities that cannot safely
run in containers. Kernel, firewall, and desktop behavior is therefore
capability-aware rather than assumed. See [Machine types](docs/MACHINE_TYPES.md).

### Security defaults

The security profile hardens SSH, the firewall, package updates, journald,
fail2ban, and service boundaries. Samba uses authenticated SMB3+, signing and
encryption, TCP 445 only, and validated configuration reloads. See the
[Samba guide](docs/SAMBA_SHARES.md) and [maintenance guide](docs/MAINTENANCE.md).

### Conservative maintenance

Automatic APT updates remain enabled, while language ecosystem upgrades and
release selection use conservative freshness and opt-in policies. Cleanup uses
bounded cache, log, journal, and temporary-artifact policies and purges packages
APT marks unused, including superseded kernels. It expires recognized crash
reports and returns unused filesystem blocks to supported physical, virtual,
and Proxmox storage, then checks block and inode pressure across local mounts.
See the
[recurring maintenance guide](docs/MAINTENANCE.md).

### Targeted updates

Use `patch` for general saved-configuration changes. Use a feature-specific
fast path when available—for example, `infra-tools shares HOST` updates Samba
users, access, paths, and share declarations without running unrelated setup
work. See [Saved configuration operations](docs/OPERATIONS.md).

## Common commands

```bash
# Inspect a saved host
infra-tools list
infra-tools info example.com

# Apply a targeted general patch
infra-tools patch example.com admin --ssl

# Update Samba shares only
infra-tools shares fileserver \
  --share write documents /srv/documents alice,bob

# Inspect and manage a Proxmox VM by its saved local name
infra-tools vm health agent-dev-01
infra-tools vm stats agent-dev-01
infra-tools vm autostart agent-dev-01
```

Use the [documentation index](docs/README.md) for the complete command and
feature map.

Agent VM setup supports narrow profile defaults or explicit tool lists,
target-side HTTPS repository clones, VM-level Git policy, transient credential
sources, and credential rotation via `infra-tools agent auth set/status`; see
the [credential guide](docs/CREDENTIALS.md) and
[command reference](docs/COMMAND_LINE.md). Codex and OpenCode can receive an
explicit, isolated Playwright capability described in the
[browser automation guide](docs/BROWSER_AUTOMATION.md).
New browsers and T3 clients can be enrolled without live terminal access by
using the [protected device-pairing portal](docs/DEVICE_PAIRING.md).
Agent-enabled targets also receive a user-scoped management launcher, and the
control system can run health checks or deliberate terminal-agent updates with
`infra-tools agent doctor HOST USER` and `infra-tools agent update HOST USER`.

## Development checks

Run the default test suite from a checkout:

```bash
make check
./run_tests.py --suite smoke
```

Routine continuous integration runs the suite in Debian Trixie on Python 3.13,
the interpreter shipped by that release. Version-tagged releases additionally
run the suite on the minimum supported Python version (3.10) and the latest
Python 3 version in the release policy (3.14). Expensive live tests remain
opt-in.

See [Saved configuration operations](docs/OPERATIONS.md) for test selectors and
[Proxmox workflows](docs/PROXMOX.md) for live-host notes.

## License

Apache License 2.0
