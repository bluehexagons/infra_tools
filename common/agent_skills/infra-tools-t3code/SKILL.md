---
name: infra-tools-t3code
description: Work with the managed T3 Code server, pairing, Git, and HTTPS endpoints on an infra-tools VM.
metadata:
  managed-by: infra_tools
---

# Managed T3 Code

Use this skill for the T3 Code server installed by infra-tools.

## Readiness

Start with:

```bash
infra-tools agent doctor --capability t3code --json
```

The server is the upstream-managed per-user service. Inspect it without sudo:

```bash
systemctl --user status t3code.service
journalctl --user -u t3code.service -n 100 --no-pager
```

The upstream unit is `~/.config/systemd/user/t3code.service`.
infra-tools keeps networking and workspace settings in
`~/.config/systemd/user/t3code.service.d/infra-tools.conf`.

## Updates

T3 Code does not silently update. The supported manual update path is:

```bash
npx t3@latest service update
```

This updates the same service managed by infra-tools. When a desktop client
requires an exact matching version, use:

```bash
npx t3@CLIENT_VERSION service update
```

Do not start a second foreground `npx t3` server on the managed port.

## Pairing

From the control system, request a one-time pairing URL:

```bash
infra-tools agent web pair HOST USER
```

Use the full returned URL. A bare T3 URL showing a pairing-key form is expected.
When protected browser enrollment is enabled, use the HTTPS pairing endpoint
and Basic Auth credentials supplied by the operator.

## Git

GitHub authentication and Git operations happen on the server as the target
user:

```bash
gh auth status
git config --global --get user.name
git config --global --get user.email
```

Keep repository remotes on HTTPS when GitHub CLI is the credential helper.
Never copy or print tokens from `~/.config/gh/hosts.yml`.
