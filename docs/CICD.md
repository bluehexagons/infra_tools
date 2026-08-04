# CI/CD Webhook System

Status: implemented. The service wiring and executor behavior now live in
code, so this note stays short and points at the relevant pieces.

Use `--cicd` during `setup` or `patch` to install the webhook receiver and
executor. Repository-specific scripts live in
`/etc/infra_tools/cicd/webhook_config.json`.

Example setup:

```bash
python3 infra_tools.py setup server_web ci.example.com deploy \
  --cicd --ssl --ssl-email admin@example.com
```

After setup, edit the generated configuration and add a GitHub webhook. The
secret is generated once and stored root-only at
`/etc/infra_tools/cicd/webhook_secret`; the systemd environment file is
`/etc/infra_tools/cicd/webhook.env`.

Core code paths:

- `web/cicd_steps.py`
- `web/service_tools/cicd_executor.py`
- [`CLOUDFLARE.md`](./CLOUDFLARE.md) for tunnel setup and webhook ingress
- [`COMMAND_LINE.md`](./COMMAND_LINE.md)

What matters operationally:

- the receiver is localhost-only behind nginx and Cloudflare tunnel
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
```

Re-run `patch` on existing app servers to replace the older deploy sudo policy
and install the privileged helper. The helper validates target names and paths
before allowing the deploy account to update an app server.

If you need the full setup flow or command syntax, use
[Command-line reference](./COMMAND_LINE.md) and
[Cloudflare tunnels](./CLOUDFLARE.md).
