# infra_tools

Automated setup and operations for Debian control planes, servers, workstations,
and Proxmox guests. infra_tools applies repeatable, machine-aware configuration over SSH,
stores redacted setup state in a workspace, and provides targeted operations
for hosts that are already configured.

## Start here

Install the current-user launcher:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
```

Then run setup commands through the installed launcher:

```bash
infra_tools setup server_web example.com admin \
  --ruby --node --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

To turn a standard Debian GNOME desktop into a control plane for managing other
VMs and containers, keep GNOME for local logins, add XFCE for RDP, and install
the desktop agent suite with the installer handoff:

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | \
  sudo sh -s -- --user "$USER" \
  --local-setup workstation_dev --control-plane --agent-suite desktop \
  --desktop xfce --rdp --rdp-existing-password
```

The [installation guide](docs/INSTALLATION.md) covers bootstrap, requirements,
credentials, workspaces, channels, upgrades, and shell completion. The
[documentation index](docs/README.md) organizes detailed feature and operations
guides. The Python entry scripts remain usable directly from a checkout for
development and recovery.

Contributors should also read the [AI agent guidance](.github/ai-agents/README.md)
before changing the project.

## Supported targets

infra_tools officially supports Debian on:

- bare-metal systems;
- virtual machines, including Proxmox VMs; and
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
| Control planes | Local VM/container administration tools, SSH/rsync, diagnostics, and optional coding agents | [Installation](docs/INSTALLATION.md), [Workstations](docs/WORKSTATIONS.md) |
| Servers | Security hardening, Nginx/SSL, Cloudflare tunnels, language runtimes, deployments, Gogs, and Antistatic | [CLI reference](docs/COMMAND_LINE.md), [Gogs](docs/GOGS.md), [Cloudflare tunnels](docs/CLOUDFLARE.md), [Antistatic](docs/ANTISTATIC.md) |
| Workstations | XFCE, i3, LXQt, RDP, browsers, and desktop tooling | [Workstations](docs/WORKSTATIONS.md), [XRDP](docs/XRDP.md), [CLI reference](docs/COMMAND_LINE.md) |
| Storage | Authenticated Samba shares, SMB mounts, rsync sync, par2 verification, and recurring operations | [Samba shares](docs/SAMBA_SHARES.md), [Storage operations](docs/STORAGE_OPERATIONS.md) |
| Deployments | Single-service deployments and `infra.json` multi-component manifests | [Deployments](docs/DEPLOYMENTS.md), [Deployment safety](docs/DEPLOYMENT_SAFETY.md), [CI/CD](docs/CICD.md) |
| Proxmox | Host discovery, VM/LXC provisioning, lifecycle, snapshots, and rolling updates | [Proxmox workflows](docs/PROXMOX.md) |
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
release selection use conservative freshness and opt-in policies. Cleanup
removes only owned, strictly named temporary artifacts and oversized journals.
See [Recurring maintenance](docs/MAINTENANCE.md).

### Targeted updates

Use `patch` for general saved-configuration changes. Use a feature-specific
fast path when available—for example, `infra_tools shares HOST` updates Samba
users, access, paths, and share declarations without running unrelated setup
work. See [Saved configuration operations](docs/OPERATIONS.md).

## Common commands

```bash
# Inspect a saved host
infra_tools list
infra_tools info example.com

# Apply a targeted general patch
infra_tools patch example.com admin --ssl

# Update Samba shares only
infra_tools shares fileserver \
  --share write documents /srv/documents alice,bob

# Manage a Proxmox guest
infra_tools proxmox health pve1 101
```

Use the [documentation index](docs/README.md) for the complete command and
feature map.

## Project direction

The [project roadmap](docs/plans/ROADMAP.md) prioritizes transactional setup and
deployment, manifest-backed secrets and CI/CD, drift detection, and tested
recovery workflows before expanding platform and provider support. The
[architectural risk review](docs/plans/ARCHITECTURAL_RISK_REVIEW_2026-08-07.md)
records the implementation risks driving that order.

## Development checks

Run the default test suite from a checkout:

```bash
make check
./run_tests.py --suite smoke
```

Continuous integration runs the suite on the minimum supported Python 3.10,
an intermediate Python 3.12, and the current stable Python 3.14. Expensive live
tests remain opt-in.

See [Saved configuration operations](docs/OPERATIONS.md) for test selectors and
[Proxmox workflows](docs/PROXMOX.md) for live-host notes.

## Repository documentation

Markdown is the source format for docs and plans so content renders directly on
GitHub and in local repository tooling. The docs index is the navigation hub;
future design notes belong under [`docs/plans/`](docs/plans/).

## License

Apache License 2.0
