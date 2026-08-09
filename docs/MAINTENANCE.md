# Recurring Maintenance

Setup flows install recurring jobs as managed systemd units. The jobs are
enabled and started after their unit files are written, and replacement units
are staged atomically so an existing working timer is not removed before its
replacement is ready. Randomized delays are used where appropriate to avoid
many hosts running the same job at the same instant.

## Installed Jobs

| Unit | Schedule | Scope |
|------|----------|-------|
| `security-monitor.timer` | Every 15 minutes | VM, bare-metal, and Proxmox host setups |
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
does not run `autoremove` or automatically remove packages. The distro timers
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
job. The `terminal` agent suite's Codex CLI, Claude Code, and OpenCode installs
do not currently have infra_tools-managed update timers; setup also skips their
installer when the command is already present. Use `infra_tools agent doctor`
to record their observed paths and versions, then update them deliberately
using their supported vendor workflow. A versioned, verified update design is
tracked in the [CLI-only agent host audit](plans/AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md).

Set `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1` in the relevant service environment
to allow global npm packages, gems, and uv-managed tools to advance. The default
is `0`.

Dependency-resolving npm and uv commands, and GitHub release selection, prefer
artifacts at least seven days old. Change the policy with
`INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS`; use `0` to disable the freshness delay.
The deployment flag `--deploy-latest DOMAIN_OR_PATH GIT_URL` explicitly bypasses
the deployment freshness policy for that repository.

## Cleanup and State Safety

`cleanup-maintenance` removes disposable APT caches, journals above the
`100M` persistent/runtime limits, and only exact infra_tools-owned temporary
artifact names older than seven days in `/tmp` and `/var/tmp`. It does not
remove installed gem versions, nvm runtimes, APT packages, or arbitrary files.

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

The implementation is shared by `lib/maintenance_systemd.py`,
`lib/update_policy.py`, `common/service_tools/cleanup_maintenance.py`, and the
service-specific updater scripts.
