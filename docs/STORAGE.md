# Storage, Backup & NAS Systems

This document describes the storage and data-protection systems in infra\_tools: how SMB sharing, rsync synchronization, and par2 integrity checking fit together to form a self-hosted NAS and backup solution.

> **Quick links:** [README](../README.md) · [Logging](LOGGING.md) · [Machine Types](MACHINE_TYPES.md)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  User Data  (local or remote filesystem)                        │
│  e.g. /mnt/data/docs, /home/user/files                         │
└──────────┬──────────────────────────────────┬───────────────────┘
           │                                  │
   ┌───────▼───────┐               ┌─────────▼─────────┐
   │  Samba (smb/)  │               │   rsync Sync       │
   │  SMB Shares    │               │   (sync/)          │
   │  SMB Mounts    │               │   systemd timers   │
   └───────┬───────┘               └─────────┬─────────┘
           │                                  │
           │  Network access                  │  Copies data to
           │  for clients                     │  backup location
           ▼                                  ▼
   ┌───────────────┐               ┌───────────────────┐
   │  Remote PCs /  │               │  Backup Dest       │
   │  File Managers  │               │  e.g. /mnt/backup  │
   └───────────────┘               └─────────┬─────────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  par2 Scrub         │
                                    │  (sync/)            │
                                    │  Data integrity     │
                                    │  + parity repair    │
                                    └─────────┬─────────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  Notifications      │
                                    │  webhook / mailbox  │
                                    └─────────────────────┘
```

The three subsystems are independent and composable:

| Subsystem | Purpose | Flag | Module |
|-----------|---------|------|--------|
| **Samba** | Expose directories as SMB/CIFS shares or mount remote shares | `--samba`, `--share`, `--mount-smb` | `smb/` |
| **Sync** | Scheduled rsync backup from source → destination | `--sync` | `sync/sync_steps.py` |
| **Scrub** | par2 parity creation, verification, and repair | `--scrub` | `sync/scrub_steps.py` |

Notifications (`--notify`) are shared across sync and scrub and send alerts via webhook or email.

---

## Samba Shares (`--samba`, `--share`)

### What it does

1. Installs and enables Samba.
2. Opens firewall ports 139/tcp and 445/tcp.
3. Applies security-hardened global settings (SMB2 minimum, no guest, fail2ban).
4. Creates per-share groups, users, and directory permissions.
5. Writes share sections into `/etc/samba/smb.conf` (idempotent — updates in-place).

### Share specification

```
--share ACCESS_TYPE SHARE_NAME PATHS USERS
```

| Argument | Description |
|----------|-------------|
| `ACCESS_TYPE` | `read` or `write` |
| `SHARE_NAME` | Name visible to SMB clients |
| `PATHS` | Comma-separated directory paths (first is primary) |
| `USERS` | Comma-separated `username:password` pairs |

```bash
# Read-only media share
--share read media /mnt/data/media guest:guest

# Read/write document share with two users
--share write documents /mnt/data/docs admin:secret,editor:pass
```

Shares are identified as `SHARE_NAME_ACCESS_TYPE` (e.g., `documents_write`) in `smb.conf`.

### Security

- SMB2 minimum protocol, no guest mapping, fail2ban (5 attempts → 1-hour ban).
- Credentials stored in Samba's own `tdb` database via `smbpasswd`.
- Users are created as system accounts with `/usr/sbin/nologin` shell.

---

## SMB Client Mounts (`--smbclient`, `--mount-smb`)

### What it does

1. Installs `cifs-utils` (via `--smbclient` or auto-enabled by `--mount-smb`).
2. Creates a systemd `.mount` unit with credentials stored in `/root/.smb/`.
3. Uses `x-systemd.automount` + `nofail` so the system boots even if the share is offline.

### Mount specification

```
--mount-smb MOUNTPOINT IP CREDENTIALS SHARE SUBDIR
```

| Argument | Description |
|----------|-------------|
| `MOUNTPOINT` | Local absolute path (e.g., `/mnt/share`) |
| `IP` | Server IP address |
| `CREDENTIALS` | `username:password` |
| `SHARE` | Remote share name |
| `SUBDIR` | Subdirectory within the share (e.g., `/docs`) |

```bash
--mount-smb /mnt/nas 192.168.1.10 user:pass documents /
```

Credentials are written to `/root/.smb/credentials-<escaped_mountpoint>` with mode `0600`.

---

## Rsync Sync (`--sync`)

### What it does

1. Installs rsync.
2. Creates a systemd oneshot service + timer for each source → destination pair.
3. Before each sync run, a Python-based mount checker validates that source and destination are accessible (especially important for SMB-mounted paths).
4. Uses `rsync -av --delete --partial` for incremental, delete-propagating backups.

### Sync specification

```
--sync SOURCE DESTINATION INTERVAL
```

| Argument | Description |
|----------|-------------|
| `SOURCE` | Absolute path to source directory |
| `DESTINATION` | Absolute path to backup destination |
| `INTERVAL` | `hourly`, `daily`, `weekly`, or `monthly` |

```bash
--sync /mnt/data/docs /mnt/backup/docs daily
```

### Systemd units created

- `sync-<source>-to-<dest>-<hash>.service` — oneshot rsync job.
- `sync-<source>-to-<dest>-<hash>.timer` — schedules the service.

### Mount safety

If either path is under `/mnt` or on an SMB mount, the service includes an `ExecCondition` that runs `check_sync_mounts.py`. If the mount is not available, the sync is skipped silently, preventing accidental writes to an empty mount point.

---

## Par2 Scrub (`--scrub`)

### What it does

1. Installs par2.
2. Creates parity (`.par2`) files for every file under a directory.
3. Periodically verifies file integrity against parity data.
4. Automatically repairs corrupted files when possible.
5. Cleans up orphan parity files when source files are deleted.

### Scrub specification

```
--scrub DIRECTORY DATABASE_PATH REDUNDANCY FREQUENCY
```

| Argument | Description |
|----------|-------------|
| `DIRECTORY` | Absolute path to the directory to protect |
| `DATABASE_PATH` | Path to the parity database directory (relative paths are resolved under `DIRECTORY`) |
| `REDUNDANCY` | Parity percentage, e.g., `5%` |
| `FREQUENCY` | `hourly`, `daily`, `weekly`, or `monthly` |

```bash
# Protect /mnt/backup/docs with 5% parity, full scrub weekly
--scrub /mnt/backup/docs .pardatabase 5% weekly
```

### Systemd units created

- `scrub-<dir>-<hash>.service` — full verify + repair run.
- `scrub-<dir>-<hash>.timer` — schedules the full scrub at `FREQUENCY`.
- `scrub-<dir>-<hash>-update.service` — parity-only update (no verify), runs hourly when the full scrub runs less frequently than hourly.
- `scrub-<dir>-<hash>-update.timer` — hourly timer for parity updates.

### Parity database

The parity database is a directory (e.g., `.pardatabase`) that mirrors the structure of the protected directory. For each file `path/to/file.txt`, the corresponding parity files are stored as `<database>/path/to/file.txt.par2`.

The database directory is automatically skipped during scrubbing to avoid recursion.

### How verification and repair work

1. `par2 verify` checks each file against its stored parity data.
2. If verification fails, `par2 repair` attempts to reconstruct the file.
3. Results are logged and reported via notifications.

---

## Combining the Systems

The typical NAS/backup pattern chains all three:

```bash
python3 setup_server_lite.py 192.168.1.10 \
  --name "HomeNAS" \
  --samba \
  --share read media /mnt/data/media guest:guest \
  --share write documents /mnt/data/docs user:pass \
  --sync /mnt/data/docs /mnt/backup/docs daily \
  --scrub /mnt/backup/docs .pardatabase 5% weekly \
  --notify webhook https://hooks.slack.com/services/... \
  --notify mailbox admin@example.com
```

**Data flow:**

1. Users read/write files via Samba shares.
2. Daily rsync copies `/mnt/data/docs` → `/mnt/backup/docs`.
3. Hourly parity updates protect new/modified files in `/mnt/backup/docs`.
4. Weekly full scrub verifies all files and repairs corruption.
5. Notifications alert on success, warnings (repairs needed), or errors.

### Mounting remote shares for sync

Use `--mount-smb` to mount a remote NAS, then sync from it:

```bash
python3 setup_server_lite.py 192.168.1.20 \
  --mount-smb /mnt/nas 192.168.1.10 user:pass documents / \
  --sync /mnt/nas /mnt/local-backup daily \
  --scrub /mnt/local-backup .pardatabase 5% weekly
```

---

## Notifications

Sync and scrub operations send notifications on completion or failure.

```bash
--notify TYPE TARGET
```

| Type | Target | Payload |
|------|--------|---------|
| `webhook` | URL | JSON POST with `subject`, `job`, `status`, `message`, `details` |
| `mailbox` | Email address | Email with `subject`, `job`, `status`, `message` |

Status values: `good`, `info`, `warning` (repairs needed), `error`.

---

## Concurrency

The `lib/concurrent_operations.py` module provides optional coordination for multiple sync/scrub operations running on the same host:

- **Memory-aware scheduling** — throttles operations when available memory is low.
- **File-level locking** — prevents two operations from writing to the same path simultaneously.
- **Priority queue** — critical operations run first.

This is used by `lib/concurrent_sync_scrub.py` to coordinate bulk operations. Single sync/scrub setups do not need this layer.

---

## Key Files

| File | Purpose |
|------|---------|
| `smb/samba_steps.py` | Samba installation, share config, user management, fail2ban |
| `smb/smb_mount_steps.py` | SMB client mount via systemd |
| `sync/sync_steps.py` | rsync service/timer creation |
| `sync/scrub_steps.py` | par2 scrub service/timer creation |
| `sync/service_tools/sync_rsync.py` | Rsync runner with notification support |
| `sync/service_tools/scrub_par2.py` | Par2 create/verify/repair with transaction support |
| `sync/service_tools/check_sync_mounts.py` | Pre-sync mount validation |
| `sync/service_tools/check_scrub_mounts.py` | Pre-scrub mount validation |
| `lib/task_utils.py` | Shared utilities: frequency validation, timer calendars, directory creation |
| `lib/mount_utils.py` | Mount point detection and validation |
| `lib/disk_utils.py` | Disk space checking and estimation |
| `lib/validation.py` | Path, service name, and redundancy validation |
| `lib/service_manager.py` | Service lifecycle management |
| `lib/concurrent_operations.py` | Concurrent operation coordination |
| `tests/test_storage.py` | Unit tests for storage core logic |

---

## Troubleshooting

### Sync not running

1. Check timer status: `systemctl list-timers | grep sync`
2. Check service logs: `journalctl -u sync-*`
3. Verify mounts: `python3 /opt/infra_tools/sync/service_tools/check_sync_mounts.py /source /dest`

### Scrub not running

1. Check timer status: `systemctl list-timers | grep scrub`
2. Check service logs: `journalctl -u scrub-*`
3. Check scrub logs: `cat /var/log/scrub/scrub-*.log`

### Samba issues

1. Test configuration: `testparm -s`
2. Check logs: `cat /var/log/samba/*.log`
3. Check user: `pdbedit -L`
4. Check firewall: `ufw status | grep -E '139|445'`

### SMB mount not available

1. Check mount status: `systemctl status <mount-unit>`
2. Test connectivity: `smbclient -L //IP -U username`
3. Check credentials: `cat /root/.smb/credentials-*`
