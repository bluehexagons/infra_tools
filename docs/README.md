# infra_tools documentation

This directory contains detailed guides for infra_tools. Start with the
[root README](../README.md) for the project overview, installation summary,
capabilities, and operating policies.

## Start here

| Guide | Use it for |
| --- | --- |
| [Installation and bootstrap](INSTALLATION.md) | Installing the launcher, preparing an orchestration host, shell completion, and requirements |
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

## Plans

Design and future-work notes live under [`plans/`](plans/):

- [Prioritized project roadmap](plans/ROADMAP.md)
- [Transactional execution and reconciliation](plans/TRANSACTIONAL_EXECUTION.md)
- [CI/CD manifest reuse](plans/CICD_MANIFEST_REUSE.md)
- [Deploy secrets and optional components](plans/DEPLOY_SECRETS.md)
- [Architectural risk review](plans/ARCHITECTURAL_RISK_REVIEW_2026-08-07.md)
- [Proxmox setup and maintenance audit](plans/PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md)
- [CLI-only agent host and maintenance audit](plans/AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md)
- [RDP desktop agent host and maintenance audit](plans/DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md)

## Documentation conventions

Markdown is the source format so the guides render directly on GitHub and in
local repository tools. Examples use `infra_tools` after installation and
`python3 infra_tools.py` when showing a checkout or bootstrap workflow; the two
forms invoke the same CLI. Examples use placeholder hosts and
credentials—never copy real secrets into documentation.
