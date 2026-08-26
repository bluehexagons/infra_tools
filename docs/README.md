# infra-tools documentation

Use the [root README](../README.md) for the project overview. This index links
to the detailed setup and operations guides.

## Release target

The operator guides describe the upcoming stable `v2.0.0` command and behavior
contract. The repository’s `dev` channel may receive changes before that tag is
published; see [Installation and bootstrap](INSTALLATION.md) for channel
selection and upgrade guidance. The `plans/` documents are implementation
references and may describe future work separately from this live contract.

## Start here

| Guide | Use it for |
| --- | --- |
| [Installation and bootstrap](INSTALLATION.md) | Installing the launcher, preparing an orchestration host, shell completion, and requirements |
| [Local system maintenance](LOCAL_MAINTENANCE.md) | Focused package, desktop, browser, hostname, IP, and DNS changes |
| [Command-line reference](COMMAND_LINE.md) | Setup, patch, targeted updates, and utility flags |
| [SSH authentication](SSH.md) | Passphrase-protected keys, terminal prompts, SSH agents, and troubleshooting |
| [Credentials and agent configuration](CREDENTIALS.md) | Workspace passwords, GitHub/Git access, agent auth, non-secret config, sharing, and rotation |
| [Authentication hardening](AUTHENTICATION_HARDENING.md) | Reachability, rate limits, failure bans, and verification for login surfaces |
| [Agent browser automation](BROWSER_AUTOMATION.md) | Playwright provisioning, Codex/OpenCode registration, verification, and security boundaries |
| [Internal HTTPS sites and previews](INTERNAL_WEB.md) | Static-site publishing, supervised live previews, managed forwards, TLS trust, and cleanup |
| [Godot Engine](GODOT.md) | Verified graphical/headless installation, web/publishing bundles, agent access, and updates |
| [T3 Code server](T3_CODE.md) | Headless service, deliberate updates, pairing, remote clients, and security boundaries |
| [Protected device pairing](DEVICE_PAIRING.md) | Basic-Auth enrollment portal, one-time provider links, rotation, removal, and security boundaries |
| [Machine types](MACHINE_TYPES.md) | Debian bare metal, VM, LXC, OCI, and capability differences |
| [Samba shares](SAMBA_SHARES.md) | Authenticated shares, credentials, access changes, removals, and SMB mounts |
| [Storage operations](STORAGE_OPERATIONS.md) | Rsync mirrors, par2 protection, schedules, locks, and recovery |
| [Generic path backups](BACKUPS.md) | Provider-neutral backup mirrors, mounted destinations, parity, and consistency limits |

## Operations and infrastructure

| Guide | Use it for |
| --- | --- |
| [Proxmox workflows](PROXMOX.md) | Host registration, VM/LXC provisioning, lifecycle, resource pressure, boot ordering, backups, and smoke tests |
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
| [Workstations and desktop applications](WORKSTATIONS.md) | Desktop profiles, human-operated browsers, Flatpak, office tools, and verification |
| [Shell completion](SHELL_COMPLETION.md) | Bash, Zsh, Fish, and system-wide completion |
| [Notifications](NOTIFICATIONS.md) | Webhook and mailbox targets shared by maintenance and operations |

## Design notes

Implementation plans and audit records live under [`plans/`](plans/). They are
development references, not operator instructions. Start with the
[planning and issue index](plans/README.md) for the active portfolio, then use
the [project roadmap](plans/ROADMAP.md) for priority and the
[GitHub issue triage](plans/GITHUB_ISSUE_TRIAGE_2026-08-17.md) for
issue-to-implementation evidence.

## Documentation conventions

Markdown is the source format so the guides render directly on GitHub and in
local repository tools. Examples use the installed `infra-tools` launcher and
placeholder hosts and credentials. Never copy real secrets into documentation.
