# infra_tools documentation

Use the [root README](../README.md) for the project overview. This index links
to the detailed setup and operations guides.

## Start here

| Guide | Use it for |
| --- | --- |
| [Installation and bootstrap](INSTALLATION.md) | Installing the launcher, preparing an orchestration host, shell completion, and requirements |
| [Local system maintenance](LOCAL_MAINTENANCE.md) | Focused package, desktop, browser, hostname, IP, and DNS changes |
| [Command-line reference](COMMAND_LINE.md) | Setup, patch, targeted updates, and utility flags |
| [Machine types](MACHINE_TYPES.md) | Debian bare metal, VM, LXC, OCI, and capability differences |
| [Samba shares](SAMBA_SHARES.md) | Authenticated shares, credentials, access changes, removals, and SMB mounts |
| [Storage operations](STORAGE_OPERATIONS.md) | Rsync mirrors, par2 protection, schedules, locks, and recovery |

## Operations and infrastructure

| Guide | Use it for |
| --- | --- |
| [Proxmox workflows](PROXMOX.md) | Host registration, VM/LXC provisioning, guest lifecycle, and smoke tests |
| [Saved configuration operations](OPERATIONS.md) | `list`, `info`, `cmd`, `deploy`, `recall`, the shell, and testing |
| [Sysadmin shortcuts](SYSADMIN.md) | SSH, transfers, health, services, logs, upgrades, and reachability |
| [Network inventory](NETWORKING.md) | Network profiles and read-only Proxmox firewall planning |
| [Recurring maintenance](MAINTENANCE.md) | Timers, update policy, cleanup, and troubleshooting |
| [Deployment safety](DEPLOYMENT_SAFETY.md) | Persistent state, backups, rollback, and deployment boundaries |
| [Deployments and manifests](DEPLOYMENTS.md) | `--deploy`, `infra.json`, static sites, services, and runtime behavior |
| [Cloudflare tunnels](CLOUDFLARE.md) | Tunnel preconfiguration, ingress refresh, firewall policy, and webhooks |

## Feature guides

| Guide | Use it for |
| --- | --- |
| [CI/CD webhook system](CICD.md) | Webhook jobs, build/app servers, and executor behavior |
| [Gogs Git service](GOGS.md) | Self-hosted Git, SSH access, storage, and release updates |
| [Antistatic services](ANTISTATIC.md) | Lobby server, report administration, STUN, and antistatic-db |
| [XRDP](XRDP.md) | Desktop RDP architecture, compatibility, and troubleshooting |
| [Workstations and desktop applications](WORKSTATIONS.md) | Desktop profiles, browsers, Flatpak, office tools, and verification |
| [Shell completion](SHELL_COMPLETION.md) | Bash, Zsh, Fish, and system-wide completion |
| [Notifications](NOTIFICATIONS.md) | Webhook and mailbox targets shared by maintenance and operations |

## Design notes

Implementation plans and audit records live under [`plans/`](plans/). They are
development references, not operator instructions. Start with the
[project roadmap](plans/ROADMAP.md).

## Documentation conventions

Markdown is the source format so the guides render directly on GitHub and in
local repository tools. Examples use the installed `infra-tools` launcher and
placeholder hosts and credentials. Never copy real secrets into documentation.
