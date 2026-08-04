# Deployment Safety Reference

This is the short reference for safety behavior that is already enforced by
code. The detailed implementation lives in the deployment and service modules;
this document focuses on what operators need to know.

## What infra_tools Does Automatically

- Creates timestamped database backups before Rails migrations when an existing
  production database is present and migrations are pending.
- Skips or allows seeds based on simple idempotency checks so existing data is
  not overwritten by accident.
- Supports `--reset-migrations` for squashed or reset migration histories.
- Keeps persistent Rails state under `.infra_tools_shared` so redeployments do
  not discard data.
- Manifest service components get dedicated runtime users and per-component
  writable state under `.infra_tools_shared/<app>/<component>`.
- Installs a weekly cleanup timer and caps journal growth on server-style
  setups.
- Uses conservative package-update policy for Node, Ruby, and uv by default.
- Installs auto-update unit files atomically and verifies that each timer is
  enabled and active without first deleting the working timer.

## Recovery Path

Backups live at:

```bash
/var/www/.infra_tools_shared/<app_name>/backups/
```

Restore the latest backup by stopping the service, copying the database back,
and starting the service again:

```bash
sudo systemctl stop rails-<app_name>.service
sudo cp /var/www/.infra_tools_shared/<app_name>/backups/<backup_file> \
       /var/www/.infra_tools_shared/<app_name>/db/production.sqlite3
sudo systemctl start rails-<app_name>.service
```

If seeds are safe to run manually, use the runtime user from the service unit:

```bash
cd /var/www/<app_directory>
APP_USER=$(systemctl show -p User --value rails-<app_name>.service)
sudo -u "$APP_USER" RAILS_ENV=production bundle exec rake db:seed
```

For a squashed or reset migration history, rerun with:

```bash
python3 infra_tools.py setup server_web <host> \
  --deploy <deploy-spec> <git-url> \
  --reset-migrations
```

## Maintenance

- `cleanup-maintenance.service` runs periodic cleanup tasks.
- `cleanup-maintenance.timer` schedules the cleanup weekly.
- `/etc/systemd/journald.conf.d/infra-tools.conf` caps journal storage at
  `100M`.
- `INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE=1` re-enables automatic Node/Ruby/uv
  package upgrades on systems where that risk is acceptable.
- Node runtime updates preserve exact global npm package versions unless the
  ecosystem auto-upgrade policy is explicitly enabled.
- Unattended APT and cleanup jobs never run `autoremove`.
- Node runtime retirement is owned by the Node updater after package migration;
  generic cleanup never removes nvm runtimes.
- Gogs release archives are checked for an executable, runnable binary before
  activation, and failed post-update checks restore the previous release.
- `INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS=7` is the default freshness cutoff for
  dependency-resolving installs that support it.

## Code References

- `lib/deployment.py`
- `lib/auto_update_systemd.py`
- `deploy/deploy_steps.py`
- `web/cicd_steps.py`
- `common/service_tools/auto_update_apt.py`
- `common/service_tools/auto_update_gogs.py`
- `common/service_tools/auto_update_ruby.py`
- `common/service_tools/auto_update_uv.py`
- `common/service_tools/auto_restart_if_needed.py`
- `security/security_steps.py`
- `tests/test_deployment_backup.py`
- `tests/test_security_steps.py`
- `tests/test_update_policy.py`

## Related Docs

- [CI/CD System](CICD.md)
- [Command-Line Reference](COMMAND_LINE.md)
- [Machine Types](MACHINE_TYPES.md)
