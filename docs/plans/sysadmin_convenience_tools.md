# Sysadmin Convenience Tools Plan

This plan covers a set of lightweight sysadmin tools added as top-level subcommands
to `infra_tools.py`. Each tool is a thin wrapper over standard Unix utilities that
reuses the existing workspace, saved-config, and SSH helpers already in the codebase.

## Goals

- Give sysadmins quick shortcuts for daily tasks (mounting, file transfer, health checks,
  bulk operations) without leaving the `infra_tools` CLI.
- Reuse saved `SetupConfig` entries so users can refer to hosts by name and inherit
  the right username, SSH key, and port automatically.
- Keep each tool small: thin argument parsing + one or two subprocess calls. No new
  external dependencies beyond `sshfs` (optional, detected at runtime).

## Non-Goals

- Replacing full-featured tools like Ansible or Fabric.
- Full idempotent provisioning logic (that lives in `setup`/`patch`).
- GUI or TUI.

## Workstreams

### 1. `mount` / `umount` — sshfs remote mounts

**Command shape:**
```
infra_tools.py mount <host>:<remote_path> <local_path> [--ro] [--username U] [--key K]
infra_tools.py umount <local_path|host>
```

Uses `sshfs` with reconnect, `ServerAliveInterval`, and `allow_other` where supported.
Auto-creates the local mountpoint. `umount` wraps `fusermount -u` / `umount` and
handles stale mounts. If host is in the saved config, pulls username/key automatically.

**Status:** Implemented — `lib/sysadmin_mount.py`, registered in `infra_tools.py`.

---

### 2. `health` — one-shot host health dump

**Command shape:**
```
infra_tools.py health <host> [--username U] [--key K]
```

SSHes into the host and prints a structured summary:
- Uptime and load average
- Memory and swap usage
- Disk usage (all mounts), highlights >85%
- Failed systemd units
- Last 10 journal errors
- Pending `apt` upgrades count
- Reboot-required flag

Falls back gracefully if individual commands are unavailable.

**Status:** Implemented — `lib/sysadmin_health.py`, registered in `infra_tools.py`.

---

### 3. `df` — multi-host disk usage table

**Status:** Implemented — `lib/sysadmin_fan.py`.

### 4. `fan` — parallel SSH fan-out

**Status:** Implemented — `lib/sysadmin_fan.py`.

### 5. `push` / `pull` — rsync wrappers

**Status:** Implemented — `lib/sysadmin_transfer.py`.

### 6. `ssh` — saved-config SSH shortcut

**Status:** Implemented — `lib/sysadmin_ssh.py`.

### 7. `key push` — idempotent pubkey install

**Status:** Implemented — `lib/sysadmin_keys.py`.

### 8. `svc` — systemctl proxy

**Status:** Implemented — `lib/sysadmin_svc.py`.

### 9. `logs` — journalctl tail

**Status:** Implemented — `lib/sysadmin_svc.py`.

### 10. `upgrade` — parallel apt upgrade

**Status:** Implemented — `lib/sysadmin_upgrade.py`.

### 11. `reachable` — SSH reachability probe

**Status:** Implemented — `lib/sysadmin_reachable.py`.

---

## File Layout

```
lib/
  sysadmin_cli.py        # argument parsing + dispatch for all sysadmin subcommands
  sysadmin_fan.py        # df, fan (parallel SSH)
  sysadmin_health.py     # health check
  sysadmin_keys.py       # key push
  sysadmin_mount.py      # mount/umount (sshfs)
  sysadmin_reachable.py  # reachable (SSH probe)
  sysadmin_ssh.py        # ssh shortcut
  sysadmin_svc.py        # svc, logs (systemctl/journalctl)
  sysadmin_transfer.py   # push/pull (rsync)
  sysadmin_upgrade.py    # upgrade (apt)
```

User-facing documentation lives in `docs/SYSADMIN.md`.
