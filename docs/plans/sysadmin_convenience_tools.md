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

**Command shape:**
```
infra_tools.py df <host> [<host2> ...] [--username U] [--key K]
```

Runs `df -h` in parallel across all listed hosts and formats the results as a
combined table sorted by percent used, with hosts >85% highlighted. Reuses
`concurrent_operations` for parallel execution.

**Status:** Planned.

---

### 4. `fan` — parallel SSH fan-out

**Command shape:**
```
infra_tools.py fan <host> [<host2> ...] -- <command> [args...]
```

Runs a shell command on multiple hosts in parallel using `concurrent_operations`,
collects stdout/stderr per host, prints a tabular summary with exit codes. A
`--group` flag can name saved host groups (stored in the workspace) for easy reuse.

**Status:** Planned.

---

### 5. `push` / `pull` — rsync wrappers

**Command shape:**
```
infra_tools.py push <local_path> <host>:<remote_path> [--dry-run] [--delete]
infra_tools.py pull <host>:<remote_path> [<local_path>] [--dry-run]
```

Thin rsync wrappers with SSH key/username from saved config, progress output,
partial-file support, and `--dry-run` mode. `push` defaults to `--dry-run` if
`--delete` is specified, requiring explicit confirmation.

**Status:** Planned.

---

### 6. `ssh` — saved-config SSH shortcut

**Command shape:**
```
infra_tools.py ssh <host> [-- <remote_command>]
```

Looks up the saved `SetupConfig` for `<host>` to get username, key, and port, then
execs into a real SSH session. Passes through arbitrary remote commands. Adds
`ControlMaster=auto` for connection reuse.

**Status:** Planned.

---

### 7. `key push` — idempotent pubkey install

**Command shape:**
```
infra_tools.py key push <host> [--pubkey ~/.ssh/id_ed25519.pub] [--username U]
```

Appends the local public key to `~/.ssh/authorized_keys` on the remote, creating
the file and directory with correct permissions if needed. Idempotent — checks for
existing key before appending.

**Status:** Planned.

---

## Implementation Order

1. `mount` / `umount` — most-requested, tangible daily use
2. `health` — immediate diagnostic value
3. `ssh` — tiny, very useful
4. `push` / `pull` — rsync wrappers
5. `key push` — small, useful for onboarding
6. `df` — multi-host variant of health disk section
7. `fan` — most complex; requires host-group storage

## File Layout

```
lib/
  sysadmin_mount.py      # mount/umount logic
  sysadmin_health.py     # health check logic
  sysadmin_transfer.py   # push/pull rsync wrappers
  sysadmin_cli.py        # shared argument parsing + dispatch for all sysadmin subcommands
```

All new modules follow the existing pattern: a `add_*_subparser()` function and a
`run_*_command()` function, wired into `infra_tools.py`'s main dispatch block.
