# Command-Line Reference

Complete reference for all setup script flags.

## Basic Flags

| Flag | Description |
|------|-------------|
| `host` | IP address or hostname (positional argument) |
| `username` | Username (positional, optional, defaults to current user) |
| `-k, --key PATH` | SSH private key path |
| `-p, --password PASS` | User password |
| `-t, --timezone TZ` | Timezone (defaults to UTC) |
| `--machine TYPE` | Machine type: `unprivileged` (LXC, default), `vm`, `privileged`, `hardware`, `oci` |
| `--name NAME` | Friendly name for this configuration |
| `--tags TAG1,TAG2` | Comma-separated tags for this configuration |
| `--dry-run` | Simulate execution without making changes |

## Desktop/Workstation Flags

| Flag | Description |
|------|-------------|
| `--rdp` / `--no-rdp` | Enable/disable RDP/XRDP (default: enabled for workstations) |
| `--audio` / `--no-audio` | Enable/disable audio setup |
| `--desktop [xfce\|i3\|cinnamon\|lxqt]` | Desktop environment (default: xfce) |
| `--browser NAME` | Browser to install (can be used multiple times) |
| `--flatpak` | Install desktop apps via Flatpak |
| `--office` | Install LibreOffice |
| `--apt-install PACKAGE` | Install package via apt |
| `--flatpak-install PACKAGE` | Install package via flatpak |
| `--dark` | Configure dark theme |

## Development Flags

| Flag | Description |
|------|-------------|
| `--ruby` | Install rbenv + Ruby + Bundler |
| `--node` | Install nvm + Node.js + PNPM |
| `--go` | Install latest Go |

## Deployment Flags

| Flag | Description |
|------|-------------|
| `--deploy DOMAIN GIT_URL` | Deploy repository to domain |
| `--full-deploy` | Always rebuild deployments |
| `--ssl` | Enable Let's Encrypt SSL |
| `--ssl-email EMAIL` | Email for SSL registration |
| `--cloudflare` | Configure Cloudflare Tunnel |
| `--api-subdomain` | Deploy Rails API to subdomain |

## Samba Flags

| Flag | Description |
|------|-------------|
| `--samba` | Install and configure Samba |
| `--share TYPE NAME PATHS USERS` | Configure Samba share |
| `--smbclient` | Install SMB/CIFS client |
| `--mount-smb MOUNT IP CREDS SHARE` | Mount SMB share persistently |

## Sync Flags

| Flag | Description |
|------|-------------|
| `--sync SOURCE DEST INTERVAL` | Configure rsync sync |

## Data Integrity Flags

| Flag | Description |
|------|-------------|
| `--scrub DIR DBPATH REDUNDANCY FREQ` | Configure par2 integrity checking |

## Notification Flags

| Flag | Description |
|------|-------------|
| `--notify TYPE TARGET` | Configure notifications (webhook or email) |

## Patch Commands

```bash
patch_setup.py list [pattern]   # List saved configurations
patch_setup.py info [pattern]    # Show configuration details
patch_setup.py rm [pattern]      # Remove configurations
patch_setup.py deploy [pattern]  # Redeploy systems
```
