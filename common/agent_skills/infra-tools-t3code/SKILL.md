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
infra-tools agent doctor --capability t3code --capability host --json
```

Treat a healthy T3 service and host-pressure warnings as separate results. The
host capability reports memory, swap, disk, agent-storage, service cgroup,
maintenance, and pending-reboot state without reading prompts, credentials, or
repository contents. Resolve critical disk pressure or failed maintenance
before starting a long build; low capacity is advisory when the service itself
is healthy.

The server is the upstream-managed per-user service. Inspect it without sudo:

```bash
systemctl --user status t3code.service
journalctl --user -u t3code.service -n 100 --no-pager
tail -n 100 ~/.t3/userdata/logs/boot-service.log
```

The upstream unit is `~/.config/systemd/user/t3code.service`.
infra-tools keeps networking and workspace settings in
`~/.config/systemd/user/t3code.service.d/infra-tools.conf`.

## Updates

T3 Code does not silently update. A connected T3 client may offer an explicit
**Update server** action for this background service. The supported host-side
update path is:

```bash
npm_config_dangerously_allow_all_scripts=true \
  npm_config_foreground_scripts=true \
  npx t3@latest service update
```

Keep those npm overrides scoped to this trusted T3 update command. npm 12 may
otherwise report success while blocking native dependency build scripts. After
an interrupted or older update, repair and verify the managed runtime with:

```bash
infra-tools agent doctor --capability t3code --fix
```

This updates the same service managed by infra-tools. When a desktop client
requires an exact matching version, use:

```bash
npm_config_dangerously_allow_all_scripts=true \
  npm_config_foreground_scripts=true \
  npx t3@CLIENT_VERSION service update
```

Do not start a second foreground `npx t3` server on the managed port.

## Browser previews

Prefer T3 Code's collaborative preview tools when they are available in the
current session. They keep navigation and evidence visible to the connected
user and do not require a second VM-local browser runtime.

Some SSH-only Codex or OpenCode sessions need an independent fallback. It is
installed only when the VM setup explicitly includes:

```bash
--browser-automation playwright
```

For that fallback, verify it with `infra-tools agent doctor --capability
browser`. Do not assume a missing Playwright capability is an error on a
T3-focused VM that uses collaborative preview.

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
