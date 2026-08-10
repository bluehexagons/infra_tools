# Recurring Maintenance

Setup flows install recurring jobs as managed systemd units. The jobs are
enabled and started after their unit files are written, and replacement units
are staged atomically so an existing working timer is not removed before its
replacement is ready. Randomized delays are used where appropriate to avoid
many hosts running the same job at the same instant.

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
| `cleanup-maintenance.timer` | Sunday at 03:30 | Server-style setups |

Container capabilities are respected. OCI containers cannot restart the system,
and security monitoring, auditd, AppArmor, and kernel-level setup are skipped
where the container cannot safely provide them. An unprivileged LXC can request
an in-container restart, but still does not receive host-kernel controls.

Inspect a job and its recent output with:

```bash
sudo systemctl status auto-update-apt.timer
sudo systemctl list-timers --all '*auto-*' '*security-monitor*' '*cleanup-*'
sudo journalctl -u auto-update-apt.service -n 100 --no-pager
```

Required host timers are verified during setup. Failure to reload, enable,
start, or confirm the security-monitor, APT-update, cleanup, or restart timer
stops setup. When the replacement APT timer cannot be verified, Debian's
existing APT timers remain enabled.

## Update Policy

APT uses the infra_tools updater instead of competing distro unattended-upgrade
timers. It runs `apt-get update` and a non-removing distribution upgrade; it
does not run `autoremove` or automatically remove packages. Before each
scheduled update, infra_tools repairs CD-ROM-only entries and stale official
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
job. The `terminal` agent suite's Codex CLI, Claude Code, and OpenCode remain
outside recurring root maintenance. Run `infra_tools agent update --dry-run`
and then `infra_tools agent update` as the setup user for a deliberate vendor
update with before/after verification, a retained prior executable, automatic
rollback after a broken update, and a private audit record. Setup still skips
an installer when its command is already present.

Set `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1` in the relevant service environment
to allow global npm packages, gems, and uv-managed tools to advance. The default
is `0`.

Dependency-resolving npm and uv commands, and GitHub release selection, prefer
artifacts at least seven days old. Change the policy with
`INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS`; use `0` to disable the freshness delay.
The deployment flag `--deploy-latest DOMAIN_OR_PATH GIT_URL` explicitly bypasses
the deployment freshness policy for that repository.

## Cleanup and State Safety

`cleanup-maintenance` removes disposable APT caches, rotates journals before
enforcing both the `100M` size ceiling and a 30-day age ceiling, invokes the
system logrotate policy, and removes only exact infra_tools-owned temporary
artifact names older than seven days in `/tmp` and `/var/tmp`.

On VMs only, the cleanup job also runs noninteractive
`apt-get autoremove --purge`. This removes packages APT has marked as unused,
including superseded kernel packages, while APT's configured kernel-retention
policy protects kernels it considers required. Physical hosts, Proxmox
hypervisors, and containers do not receive scheduled package removal. Cleanup
never removes installed gem or nvm runtime versions or arbitrary files.

Storage synchronization and scrub jobs write scheduling state atomically and
use a persistent lock inode to prevent overlapping runs. Invalid specifications
or unavailable mounts fail visibly so the next scheduled run can retry them.

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
