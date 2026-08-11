# CI/CD Webhook System

Use `--cicd` during `setup` or `patch` to install the webhook receiver and
executor. Repository-specific scripts live in
`/etc/infra_tools/cicd/webhook_config.json`.

Example setup:

```bash
infra-tools setup server_web ci.example.com deploy \
  --cicd --ssl --ssl-email admin@example.com
```

After setup, edit the generated configuration and add a GitHub webhook. The
secret is generated once and stored root-only at
`/etc/infra_tools/cicd/webhook_secret`; the systemd environment file is
`/etc/infra_tools/cicd/webhook.env`.

## Build and app server topology

The build server runs the webhook receiver and builds as the dedicated
`webhook` user. An app server only needs nginx, rsync, and the restricted
`deploy` account. The build server pushes artifacts over SSH; it does not need
root access on the app server.

Set up the app server first:

```bash
infra-tools setup server_web app.example.com deploy \
  --app-server --ssl --ssl-email admin@example.com
```

Then set up the build server and name each target (repeat
`--deploy-target` for multiple app servers):

```bash
infra-tools setup server_web build.example.com deploy \
  --build-server --cicd --node --python \
  --deploy-target app.example.com
```

The build setup creates the deploy key at
`/var/lib/infra_tools/cicd/.ssh/deploy_key`. Copy its `.pub` file into
`/home/deploy/.ssh/authorized_keys` on every app server. The setup also writes
`/etc/infra_tools/cicd/deploy_targets.json` and scans each target into
`/var/lib/infra_tools/cicd/known_hosts`; verify those host fingerprints before
the first production deployment.

The target entries default to the `deploy` user, SSH port 22, and `/var/www`.
Edit the JSON only when a target needs a different port, base directory, or
key path. The target name used by a repository must match its JSON key.

## Repository configuration

Edit `/etc/infra_tools/cicd/webhook_config.json` on the build server. Each
repository entry selects accepted branches and scripts. A remote deployment
uses `deploy_target` (a key from `deploy_targets.json`) and an optional
`deploy_spec` (`domain` or `domain/path`):

```json
{
  "repositories": [
    {
      "url": "https://github.com/example/site.git",
      "branches": ["main"],
      "deploy_target": "app.example.com",
      "deploy_spec": "www.example.com/",
      "scripts": {
        "install": "scripts/install.sh",
        "build": "scripts/build.sh",
        "test": "scripts/test.sh",
        "deploy": "scripts/deploy.sh"
      }
    }
  ]
}
```

`install`, `build`, and `test` run in a fresh, commit-pinned workspace as
`webhook`. When `deploy_target` is present, artifacts are pushed with rsync,
nginx configuration is refreshed, and the optional deploy script is streamed
to the target directory. Without `deploy_target`, the optional deploy script
runs locally on the build server. Use repository URLs without embedded
credentials; the executor rejects credential-bearing URLs.

After changing the JSON, the next signed push uses the new settings. A ping
event only verifies webhook connectivity and does not build a repository.

## Security and execution boundaries

- the receiver is localhost-only behind Nginx; expose it through Cloudflare
  Tunnel when that option is configured
- webhook signatures are verified with the stored secret
- webhook bodies are capped at 1 MiB and push fields are validated before queueing
- the executor uses a fresh clone with Git hooks disabled, then checks out the
  signed commit SHA only after verifying it is reachable from the configured
  branch
- repository workspaces include a URL digest, preventing same-name repositories
  from sharing a checkout
- HTTP repository URLs with embedded credentials are rejected so secrets cannot
  leak through queue files or build logs; use the configured Git credential helper
- app-server privilege is exposed only through the validating
  `infra-tools-deploy-admin` helper; the deploy account has no wildcarded root
  `rm`, `mkdir`, or `touch` access
- build logs live under `/var/lib/infra_tools/cicd/logs/`
- build scripts run as the dedicated `webhook` user
- `--build-server --node` and `--build-server --python` bootstrap the build
  toolchains for that user
- the receiver writes one bounded job file and the path unit starts the
  executor, so the receiver does not need systemd or polkit privileges
- jobs are consumed after one attempt, including malformed or failed jobs, so
  one bad payload cannot retrigger forever

Quick checks:

```bash
sudo systemctl status webhook-receiver.service
sudo journalctl -u webhook-receiver.service -f
sudo journalctl -u cicd-executor.service -f
sudo systemctl status cicd-executor.path
curl -fsS http://127.0.0.1:8080/webhook/health
```

Run `patch` on existing app servers to apply the deploy sudo policy and install
the privileged helper. The helper validates target names and paths before
allowing the deploy account to update an app server.

If you need the full setup flow or command syntax, use
[Command-line reference](./COMMAND_LINE.md) and
[Cloudflare tunnels](./CLOUDFLARE.md).
