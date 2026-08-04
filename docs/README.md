# infra_tools documentation

This directory contains detailed guides for infra_tools. Start with the
[root README](../README.md) for the project overview, installation summary,
capabilities, and operating policies.

## Start here

| Guide | Use it for |
| --- | --- |
| [Installation and bootstrap](INSTALLATION.md) | Installing the launcher, preparing an orchestration host, shell completion, and requirements |
| [Command-line reference](COMMAND_LINE.md) | Setup, patch, fast-update, and utility flags |
| [Machine types](MACHINE_TYPES.md) | Debian bare metal, VM, LXC, OCI, and capability differences |
| [Samba shares](SAMBA_SHARES.md) | Authenticated shares, credentials, access changes, removals, and SMB mounts |

## Operations and infrastructure

| Guide | Use it for |
| --- | --- |
| [Proxmox workflows](PROXMOX.md) | Host registration, VM/LXC provisioning, guest lifecycle, and smoke tests |
| [Saved configuration operations](OPERATIONS.md) | `list`, `info`, `cmd`, `deploy`, `recall`, the shell, and testing |
| [Sysadmin shortcuts](SYSADMIN.md) | SSH, transfers, health, services, logs, upgrades, and reachability |
| [Network inventory](NETWORKING.md) | Network profiles and read-only Proxmox firewall planning |
| [Recurring maintenance](MAINTENANCE.md) | Timers, update policy, cleanup, and troubleshooting |
| [Deployment safety](DEPLOYMENT_SAFETY.md) | Persistent state, backups, rollback, and deployment boundaries |

## Feature guides

| Guide | Use it for |
| --- | --- |
| [CI/CD webhook system](CICD.md) | Webhook jobs, build/app servers, and executor behavior |
| [Antistatic services](ANTISTATIC.md) | Lobby server, report administration, STUN, and antistatic-db |
| [XRDP](XRDP.md) | Desktop RDP architecture, compatibility, and troubleshooting |
| [Shell completion](SHELL_COMPLETION.md) | Bash, Zsh, Fish, and system-wide completion |

## Plans

Design and future-work notes live under [`plans/`](plans/):

- [CI/CD manifest reuse](plans/CICD_MANIFEST_REUSE.md)
- [Deploy secrets and optional components](plans/DEPLOY_SECRETS.md)

## Documentation conventions

Markdown is the source format so the guides render directly on GitHub and in
local repository tools. Commands are written for the installed `infra_tools`
launcher where possible; `python3 infra_tools.py` is equivalent from a
checkout. Examples use placeholder hosts and credentials—never copy real
secrets into documentation.
