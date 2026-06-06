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

If you need the full setup flow or command syntax, use
[`docs/COMMAND_LINE.md`](./COMMAND_LINE.md) and
[`web/config/webhook_cloudflare_setup.md`](../web/config/webhook_cloudflare_setup.md).
