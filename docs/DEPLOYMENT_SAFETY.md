# Deployment Safety Reference

This reference summarizes the deployment safety behavior operators need to
know.

## Automatic safeguards

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
- Installs recurring maintenance unit files atomically and verifies that each
  timer is enabled and active without first deleting the working timer.
- Validates Nginx hardening and default-site changes before reload, restoring
  the exact previous configuration when validation fails.
- Applies a seven-day freshness delay to dependency resolution and GitHub release
  selection unless the operator opts into a newer release.

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
infra_tools setup server_web <host> \
  --deploy <deploy-spec> <git-url> \
  --reset-migrations
```

## Maintenance

Deployment hosts install the same managed cleanup, update, restart, and
journaling controls described in [`MAINTENANCE.md`](./MAINTENANCE.md). The
deployment-specific guarantees are:

- cleanup never runs `autoremove` or removes installed runtimes;
- restart checks fail safe when uptime or active-session detection is
  unavailable;
- Gogs release activation validates the new binary and restores the previous
  release after a failed post-update check; and
- dependency-resolving installs use a seven-day freshness delay unless
  `--deploy-latest DOMAIN_OR_PATH GIT_URL` explicitly opts out.

## Related guides

- [CI/CD System](CICD.md)
- [Recurring Maintenance](MAINTENANCE.md)
- [Command-Line Reference](COMMAND_LINE.md)
- [Machine Types](MACHINE_TYPES.md)
