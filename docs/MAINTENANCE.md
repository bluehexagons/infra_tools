# Recurring Maintenance

Setup flows install recurring jobs as managed systemd units. The jobs are
enabled and restarted after their unit files are written, so rerunning setup
immediately applies a changed schedule. Replacement units are staged atomically
so an existing working timer is not removed before its replacement is ready.
Randomized delays are used where appropriate to avoid many hosts running the
same job at the same instant.

## Installed Jobs

| Unit | Schedule | Scope |
|------|----------|-------|
| `security-monitor.timer` | Every 15 minutes | VM, bare-metal, and Proxmox host security events; XRDP certificate health when configured |
| `auto-update-apt.timer` | Daily at 06:00 | Security-enabled setups |
| `auto-restart-if-needed.timer` | Daily at 02:00 and 30 minutes after boot | Kernel-capable machines; saved policy chooses restart or deferral |
| `auto-update-node.timer` | Sunday at 03:00 | Setups with Node.js/nvm |
| `auto-update-uv.timer` | Sunday at 05:00 | Setups with Python and uv |
| `auto-update-gogs.timer` | Sunday at 05:30 | Setups with Gogs |
| `auto-update-godot.timer` | Sunday at 06:30 | Setups with Godot; also reconciles selected Godot bundles |
| `cleanup-maintenance.timer` | Sunday at 03:30 | Security-enabled setups |
| `user-cache-maintenance.timer` | Monday at 03:00 | Security-enabled setups with a non-root setup user |

Container capabilities are respected. OCI containers cannot restart the system,
and security monitoring, auditd, AppArmor, and kernel-level setup are skipped
where the container cannot safely provide them. An unprivileged LXC can request
an in-container restart, but still does not receive host-kernel controls.

Inspect a job and its recent output with:

```bash
sudo systemctl status auto-update-apt.timer
sudo systemctl list-timers --all '*auto-*' '*security-monitor*' '*cache-maintenance*'
sudo journalctl -u auto-update-apt.service -n 100 --no-pager
```

Required host timers are verified during setup. Failure to reload, enable,
start, or confirm the security-monitor, APT-update, cleanup, user-cache, or
restart timer stops setup. When the replacement APT timer cannot be verified,
Debian's existing APT timers remain enabled.
`infra-tools agent doctor --capability host` also reports installed Node and
Godot update timers, while omitting those optional jobs on VMs where their
toolchains were not selected.

## Update Policy

APT uses the infra-tools updater instead of competing distro unattended-upgrade
timers. It runs `apt-get update` and a non-removing distribution upgrade; it
does not run `autoremove` or automatically remove packages. Before each
scheduled update, infra-tools repairs CD-ROM-only entries and stale official
Debian suites using the installed release codename. The distro timers
are disabled only after the replacement timer is enabled, started, and verified.

Node.js and uv use a conservative default policy:

- Node.js follows the LTS track by default. An already-installed non-LTS track
  is treated as an explicit choice and remains on that track. Global npm
  package versions are preserved when the runtime changes. If package migration
  fails, the updater restores the previous default and removes only the
  incomplete new runtime. A later setup rerun verifies the promised
  Node/npm/PNPM baseline and repairs it if a manual change left one of those
  commands unavailable.
- uv updates the uv executable itself, but uv-managed tools are upgraded only
  when ecosystem upgrades are enabled.
- Gogs validates a downloaded release before activation and rolls back the
  previous release when post-update commands or restart fail.
- Godot follows the newest stable upstream release without the general
  seven-day freshness delay. The publisher-provided SHA-256 is verified before
  a versioned release is activated through the system-wide launchers. Its web
  bundle installs matching verified export templates for registered users;
  the publishing bundle updates verified Butler releases and invokes the
  user-owned SteamCMD self-updater.

Upgrading a host retires the old `auto-update-ruby` service and timer. It does
not uninstall the Ruby packages or stop an existing legacy Rails application.

GitHub CLI is installed from its APT repository and therefore follows the APT
job. Explicitly selected Codex CLI, Claude Code, and OpenCode installations
remain outside recurring root updates; their rebuildable caches are covered
by the separate user maintenance job. T3 Code's per-user service is also not
silently updated. Use the client's **Update server** action, the npm 12-safe
host command in [`T3_CODE.md`](T3_CODE.md), or rerun setup with
`--refresh-packages`. Run
`infra-tools agent update --dry-run` and then `infra-tools agent update` as the
account that owns the terminal tools (for example,
`sudo -u agent -H infra-tools agent update --tool codex`) for a deliberate
terminal-agent vendor update with before/after verification, a retained prior
executable, automatic rollback after a broken update, and a private audit
record. After a non-dry-run update, infra-tools also records a redacted
tools-and-host readiness result, including T3 Code when it is installed. The
update command exits nonzero if that audit is unhealthy or cannot be saved.
The update environment is reset to that account's home so a caller's working
directory and PATH cannot redirect the vendor installer. Setup still skips an
installer when its command is already present.

From the control system, the equivalent remote workflow is
`infra-tools agent update HOST USER --dry-run` followed by the same command
without `--dry-run`; use `--tool` to narrow either operation. Agent-enabled
setups install the target-user launcher needed for local VM maintenance as
part of the normal reconciliation.

After a deliberate T3 Code update or host reboot, run and persist the
composite readiness check as the target account:

```bash
infra-tools agent doctor --capability t3code --capability host --record
infra-tools agent doctor --last-record --json
```

The private mode-`0600` record contains the boot ID and redacted aggregate
results, not paths, Git identity, credential contents, repository contents, or
process details. Reading a healthy record from a previous boot still exits
nonzero, which prevents old evidence from being mistaken for a post-reboot
check. The same `--record` and `--last-record` options work with the remote
`HOST USER` doctor form.

If a vendor command is run directly, use the same account and working
directory, such as `sudo -u agent -H sh -lc 'cd /home/agent && codex update'`.

Set `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1` in the relevant service environment
to allow global npm packages and uv-managed tools to advance. The default
is `0`.

Dependency-resolving npm and uv commands, and GitHub release selection, prefer
artifacts at least seven days old. Change the policy with
`INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS`; use `0` to disable the freshness delay.
The deployment flag `--deploy-latest DOMAIN_OR_PATH GIT_URL` explicitly bypasses
the deployment freshness policy for that repository.

Privileged Go, Godot, Butler, Gogs, and managed binary downloads use private,
randomly named temporary directories. They never download through a
predictable public `/tmp` filename that another local account could replace
with a symbolic link.
Release tags are restricted to safe path components, release assets require
credential-free HTTPS URLs without protocol-downgrade redirects, and Go
archives require the official feed's full SHA-256 digest before extraction.

## Cleanup and State Safety

`cleanup-maintenance` removes disposable APT caches, rotates journals before
enforcing both the `100M` size ceiling and a 30-day age ceiling, invokes the
system logrotate policy, removes recognized crash-report files older than 30
days, and removes only exact infra_tools-owned temporary artifact names older
than seven days in `/tmp` and `/var/tmp`.

The cleanup job also runs noninteractive `apt-get autoremove --purge` wherever
APT is available. This removes packages APT has marked as unused, including
superseded kernel packages, while APT's configured kernel-retention policy
protects kernels it considers required. It deliberately retains configuration
remnants for packages that were already removed: blanket residual purges can
run maintainer hooks for service names now owned by installed replacement
packages. It then audits `dpkg` state and reports incomplete or inconsistent
packages without attempting an automatic repair. On physical machines, VMs,
and Proxmox hosts, cleanup returns unused blocks to storage after deletion when
discard is supported. It defers to an active native `fstrim.timer` instead of
running a duplicate trim; containers skip this host-level operation.

`user-cache-maintenance` runs as the configured non-root account instead of
root, after the weekly runtime-update window. It inventories tool-reported
cache paths before acting. Tool commands receive the account's home-scoped
environment without loading interactive login profiles, and apply these
bounded policies:

- npm runs its supported verification and garbage collection, then uses a
  forced clean only if the cache still exceeds 2 GiB. Its separately
  rebuildable `_npx` workspaces are removed when they exceed 1 GiB or have had
  no activity for 30 days, and only while npm and npx are idle;
- pip purges only above 2 GiB, uv runs its supported prune operation, and Go
  cleans build and module caches only above 2 GiB and 5 GiB respectively; and
- OpenCode and Codex cleanup is restricted to rebuildable cache directories.
  The OpenCode cache limit is 2 GiB and the Codex cache limit is 1 GiB; either
  cache may also be removed after 90 days without activity. Codex temporary
  entries older than seven days are removed individually. Standalone Codex
  installations retain the current release, the newest prior release for
  rollback, and every release currently executing. Older releases are removed
  only after their vendor manifest, entrypoint, ownership, and directory layout
  have been validated; unfamiliar entries are left unchanged.
- T3 Code numbered provider and trace log rotations are retained up to 256 MiB
  and 14 days. Current logs, terminal logs, non-numbered files, and symbolic
  links are never selected by this policy. Agent setup reruns apply both the
  Codex release policy and T3 rotation policy immediately, in addition to the
  weekly maintenance job. Setup invokes this reconciliation as the target
  account rather than with its own root privileges.

Agent cache cleanup is deferred while the matching tool is running. Symbolic
links and paths outside the configured user's home are never followed or
removed. OpenCode data under `.local/share/opencode` and Codex sessions,
memories, credentials, plugins, and unrecognized package layouts are persistent
state and are not cleanup targets. Root-only setups retain system cleanup but
intentionally skip the user-cache timer. Preview the user job without changing
files with:

```bash
sudo -u USER /usr/bin/python3 \
  /opt/infra_tools/common/service_tools/user_cache_maintenance.py --dry-run
```

Cleanup never removes installed language runtime versions, Proxmox backups,
templates, ISOs, guest volumes, container/image stores, crash-report
directories, or arbitrary files. Proxmox boot entries and pinned kernels remain
under APT and `proxmox-boot-tool` retention policy.

After cleanup, capacity checks cover each distinct real local filesystem rather
than only `/`. Both block usage and inode usage trigger warnings at 80% and
errors at 90%, so a separate Proxmox storage mount cannot fill silently while
the root filesystem remains healthy. Network and FUSE mounts are excluded to
avoid blocking maintenance on unavailable remote storage.

Storage synchronization and scrub jobs write scheduling state atomically and
use current-user-owned, mode-`0700` lock directories under
`/run/lock/infra_tools`; lock files are regular mode-`0600` files and retain a
persistent inode to prevent overlapping runs. Invalid specifications or
unavailable mounts fail visibly so the next scheduled run can retry them.

## Agent Maintenance Holds

Before starting agent work that must survive the normal automatic-restart
window, create a bounded hold as the account that owns the agent tools:

```bash
infra-tools agent maintenance hold --hours 8
infra-tools agent maintenance status
infra-tools agent maintenance release
```

The hold is a private, atomic file below the account's home and expires without
manual cleanup. Durations are limited to 1–72 hours. Creating another hold
renews it; release is idempotent. The same operation can be requested from a
control system with `infra-tools agent maintenance hold HOST USER --hours 8`.

When a restart is pending, the existing restart job also defers for recognized
coding-agent, build, Git, terminal-multiplexer, and managed agent-worktree
processes owned by the configured setup account. It records only workload
categories: process command lines, prompts, and repository contents are not
read, while working directories are used only to test membership in the fixed
managed-worktree root and are never recorded. An invalid hold fails safe and
is visible in `infra-tools agent doctor --capability host`; release and
recreate it. The configured forced-restart deadline still overrides sessions,
holds, and workloads after its maximum deferral period.

## Related Configuration

- `--auto-restart` / `--no-auto-restart` controls normal automatic restarts.
- `--auto-restart-force-days N` sets the maximum deferral period; `0` disables
  forced restarts.
- `--auto-restart-grace N` sets the warning period before a restart.
- `infra-tools agent maintenance hold|status|release` manages a temporary,
  per-user automatic-restart hold without changing the host's saved policy.
- Notification targets configured with `--notify` receive important maintenance
  failures and successes where the service supports notifications.
- Security monitoring always collects and logs locally. Without `--notify`, it
  does not send events off-host.

On XRDP hosts, the security monitor validates certificate/key syntax, match,
expiry, private-key permissions, and daemon readability. It notifies only when
health changes (including recovery or certificate fingerprint rotation), while
an unusable pair keeps the service result failed until repaired. The warning
window is 30 days. The monitor never logs or records private-key contents.
