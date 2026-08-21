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
| `auto-update-ruby.timer` | Sunday at 04:00 | Setups with Ruby and `gem` |
| `auto-update-uv.timer` | Sunday at 05:00 | Setups with Python and uv |
| `auto-update-gogs.timer` | Sunday at 05:30 | Setups with Gogs |
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

## Update Policy

APT uses the infra-tools updater instead of competing distro unattended-upgrade
timers. It runs `apt-get update` and a non-removing distribution upgrade; it
does not run `autoremove` or automatically remove packages. Before each
scheduled update, infra-tools repairs CD-ROM-only entries and stale official
Debian suites using the installed release codename. The distro timers
are disabled only after the replacement timer is enabled, started, and verified.

Node.js, Ruby, and uv use a conservative default policy:

- Node.js follows the LTS track by default. An already-installed non-LTS track
  is treated as an explicit choice and remains on that track. Global npm
  package versions are preserved when the runtime changes.
- Ruby updates the managed global gems only when ecosystem upgrades are enabled.
- uv updates the uv executable itself, but uv-managed tools are upgraded only
  when ecosystem upgrades are enabled.
- Gogs validates a downloaded release before activation and rolls back the
  previous release when post-update commands or restart fail.

GitHub CLI is installed from its APT repository and therefore follows the APT
job. Explicitly selected Codex CLI, Claude Code, and OpenCode installations
remain outside recurring root updates; their rebuildable caches are covered
by the separate user maintenance job. T3 Code's current desktop installation
has no managed update path. Run `infra-tools agent update --dry-run` and then
`infra-tools agent update` as the account that owns the tools (for example,
`sudo -u agent -H infra-tools agent update --tool codex`) for a deliberate
terminal-agent vendor update with before/after verification, a retained prior
executable, automatic rollback after a broken update, and a private audit
record. The update environment is reset to that account's home so a caller's
working directory and PATH cannot redirect the vendor installer. Setup still
skips an installer when its command is already present.

From the control system, the equivalent remote workflow is
`infra-tools agent update HOST USER --dry-run` followed by the same command
without `--dry-run`; use `--tool` to narrow either operation. Agent-enabled
setups install the target-user launcher needed for local VM maintenance as
part of the normal reconciliation.

If a vendor command is run directly, use the same account and working
directory, such as `sudo -u agent -H sh -lc 'cd /home/agent && codex update'`.

Set `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1` in the relevant service environment
to allow global npm packages, gems, and uv-managed tools to advance. The default
is `0`.

Dependency-resolving npm and uv commands, and GitHub release selection, prefer
artifacts at least seven days old. Change the policy with
`INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS`; use `0` to disable the freshness delay.
The deployment flag `--deploy-latest DOMAIN_OR_PATH GIT_URL` explicitly bypasses
the deployment freshness policy for that repository.

Privileged Go, Gogs, and managed binary downloads use private, randomly named
temporary directories. They never download through a predictable public
`/tmp` filename that another local account could replace with a symbolic link.
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
protects kernels it considers required. It also purges configuration remnants
for packages that were already removed, then audits `dpkg` state and reports
incomplete or inconsistent packages without attempting an automatic repair. On
physical machines, VMs, and Proxmox hosts, cleanup returns unused blocks to
storage after deletion when discard is supported. It defers to an active native
`fstrim.timer` instead of running a duplicate trim; containers skip this
host-level operation.

`user-cache-maintenance` runs as the configured non-root account instead of
root, after the weekly runtime-update window. It inventories tool-reported
cache paths before acting. Tool commands receive the account's home-scoped
environment without loading interactive login profiles, and apply these
bounded policies:

- npm runs its supported verification and garbage collection, then uses a
  forced clean only if the cache still exceeds 2 GiB;
- pip purges only above 2 GiB, uv runs its supported prune operation, and Go
  cleans build and module caches only above 2 GiB and 5 GiB respectively; and
- OpenCode and Codex cleanup is restricted to rebuildable cache directories.
  The OpenCode cache limit is 2 GiB and the Codex cache limit is 1 GiB; either
  cache may also be removed after 90 days without activity. Codex temporary
  entries older than seven days are removed individually.

Agent cache cleanup is deferred while the matching tool is running. Symbolic
links and paths outside the configured user's home are never followed or
removed. OpenCode data under `.local/share/opencode` and Codex sessions,
memories, credentials, packages, and plugins are persistent state and are not
cleanup targets. Root-only setups retain system cleanup but intentionally skip
the user-cache timer. Preview the user job without changing files with:

```bash
sudo -u USER /usr/bin/python3 \
  /opt/infra_tools/common/service_tools/user_cache_maintenance.py --dry-run
```

Cleanup never removes installed gem or nvm runtime versions, Proxmox backups,
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

## Related Configuration

- `--auto-restart` / `--no-auto-restart` controls normal automatic restarts.
- `--auto-restart-force-days N` sets the maximum deferral period; `0` disables
  forced restarts.
- `--auto-restart-grace N` sets the warning period before a restart.
- Notification targets configured with `--notify` receive important maintenance
  failures and successes where the service supports notifications.
- Security monitoring always collects and logs locally. Without `--notify`, it
  does not send events off-host.

On XRDP hosts, the security monitor validates certificate/key syntax, match,
expiry, private-key permissions, and daemon readability. It notifies only when
health changes (including recovery or certificate fingerprint rotation), while
an unusable pair keeps the service result failed until repaired. The warning
window is 30 days. The monitor never logs or records private-key contents.
