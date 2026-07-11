# CI/CD Webhook System

Status: implemented. The service wiring and executor behavior now live in
code, so this note stays short and points at the relevant pieces.

Use `--cicd` during `setup` or `patch` to install the webhook receiver and
executor. Repository-specific scripts live in
`/etc/infra_tools/cicd/webhook_config.json`.

Core code paths:

- `web/cicd_steps.py`
- `web/service_tools/cicd_executor.py`
- `web/config/webhook_cloudflare_setup.md`
- `docs/COMMAND_LINE.md`

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

Quick checks:

```bash
sudo systemctl status webhook-receiver.service
sudo journalctl -u webhook-receiver.service -f
sudo journalctl -u cicd-executor.service -f
```

Failed and malformed queue entries are consumed after one attempt so a bad job
cannot keep the systemd path unit in a restart loop. Re-run `patch` on existing
app servers to replace the older deploy sudo policy and install the privileged
helper.

If you need the full setup flow or command syntax, use
[`docs/COMMAND_LINE.md`](./COMMAND_LINE.md) and
[`web/config/webhook_cloudflare_setup.md`](../web/config/webhook_cloudflare_setup.md).
