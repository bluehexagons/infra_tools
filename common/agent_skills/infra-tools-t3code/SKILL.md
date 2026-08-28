---
name: infra-tools-t3code
description: Operate and troubleshoot the managed T3 Code server, pairing flow, and server-side Git environment on an infra-tools VM.
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

Treat T3 service readiness and host-pressure warnings as separate results. Use
the `infra-tools-vm-triage` skill for host pressure or a support snapshot.

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

T3 Code does not silently update. Prefer the connected client's explicit
**Update server** action. For a host-side update, set `T3_RELEASE` to `latest`
or the exact version required by the client, then run:

```bash
T3_RELEASE=latest
env -u npm_config_dangerously_allow_all_scripts \
  -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
  -u npm_config_allow_scripts \
  -u NPM_CONFIG_ALLOW_SCRIPTS \
  CC=gcc \
  CXX=g++ \
  npm_config_strict_allow_scripts=false \
  npm_config_foreground_scripts=true \
  npx --yes --package="t3@$T3_RELEASE" -c \
  'env -u npm_config_allow_scripts \
    -u NPM_CONFIG_ALLOW_SCRIPTS \
    -u npm_config_dangerously_allow_all_scripts \
    -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
    t3 service update'
infra-tools agent doctor --capability t3code --fix
```

Keep those npm settings scoped to this trusted T3 update command. npm 12
rejects inherited `allow-scripts` and `dangerously-allow-all-scripts` settings
in T3's nested runtime. The doctor performs the bounded native-module repair
and verifies the service. `infra-tools agent update` is not a T3 updater; it
updates selected Codex, Claude Code, and OpenCode installations. Do not start a
second foreground T3 server on the managed port.

## Long-running work

Use the `infra-tools-agent-operations` skill for bounded maintenance holds and
redacted readiness records. Release a hold promptly after protected work.

## Browser previews

Use the `infra-tools-browser-testing` skill. Prefer T3 Code's collaborative
preview when attached; the optional VM-local browser is only an SSH fallback.

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
git config --global --get init.defaultBranch
```

Keep repository remotes on HTTPS when GitHub CLI is the credential helper.
Never copy or print tokens from `~/.config/gh/hosts.yml`.

infra-tools configures new repositories to use `main` unless the user already
selected another global default. An unborn repository has no branch ref until
its first commit: rename its symbolic branch with `git branch -m main`; do not
use `git branch main`, which requires an existing commit and fails in T3's
create-branch action. Create the initial commit before creating or switching to
additional branches.
