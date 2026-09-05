# infra-tools quick reference

Use this page to find the right command family and detailed guide. It is not a
replacement for the [command-line reference](COMMAND_LINE.md): read that page
before combining advanced options or changing a production host.

## Common host lifecycle

| Goal | Command | Details |
| --- | --- | --- |
| Preview a new setup | `infra-tools setup server_lite server.example admin --ssl --dry-run` | [Installation](INSTALLATION.md#install-and-configure-a-remote-host) |
| Set up a new host | `infra-tools setup server_lite server.example admin --ssl` | [CLI reference](COMMAND_LINE.md#setup-at-a-glance) |
| List saved hosts | `infra-tools list` | [Saved configuration operations](OPERATIONS.md#inspect-saved-hosts) |
| Inspect a saved host | `infra-tools info server.example` | [Saved configuration operations](OPERATIONS.md#inspect-saved-hosts) |
| View its saved command | `infra-tools cmd server.example` | [Saved configuration operations](OPERATIONS.md#recall-and-reconstruction) |
| Change saved configuration | `infra-tools patch server.example admin --ssl` | [Saved configuration operations](OPERATIONS.md#patch-and-redeploy) |
| Update shares only | `infra-tools shares fileserver` | [Samba shares](SAMBA_SHARES.md) |
| Deploy a saved host | `infra-tools deploy server.example --yes` | [Deployments](DEPLOYMENTS.md#basic-deployment) |

Replace the examples with the actual system type, host, user, and options for
your environment. Use `--dry-run` before a first setup or a consequential
change.

## Find a task

| I need to… | Use |
| --- | --- |
| Install or upgrade the controller | [Installation and bootstrap](INSTALLATION.md) |
| Understand a flag or command not shown above | [Command-line reference](COMMAND_LINE.md) |
| Connect, copy files, inspect logs, or check a service | [Sysadmin shortcuts](SYSADMIN.md) |
| Configure SSH keys or passphrases | [SSH authentication](SSH.md) |
| Manage recurring jobs, updates, or cleanup | [Recurring maintenance](MAINTENANCE.md) |
| Provision and operate a Proxmox VM or LXC | [Proxmox workflows](PROXMOX.md) |
| Change a local controller or workstation | [Local system maintenance](LOCAL_MAINTENANCE.md) |
| Configure notification destinations or alert volume | [Notifications](NOTIFICATIONS.md) |
| Inspect audit activity or receive remote notification logs | [Minimal web panel](WEB_PANEL.md) |
| Publish an internal site or preview | [Internal HTTPS sites and previews](INTERNAL_WEB.md) |
| Deploy an application or manifest | [Deployments and manifests](DEPLOYMENTS.md) |
| Configure CI/CD | [CI/CD webhook system](CICD.md) |
| Configure shares, sync, parity, or backups | [Storage and data guides](README.md#services-deployments-and-data) |
| Provision or operate a coding VM | [Agent systems](agents/README.md) |

## Safe operating habits

- Inspect a saved host with `info` and `cmd` before a broad patch.
- Keep passwords and token-bearing webhook URLs out of shared output and
  tickets.
- Use feature-specific commands such as `shares` when they cover the intended
  change; they avoid unrelated setup work.
- Check [Machine types](MACHINE_TYPES.md) before expecting a kernel, firewall,
  desktop, or service capability in a container.

For the complete documentation map, return to the
[documentation index](README.md).
