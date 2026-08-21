---
name: infra-tools-t3code
description: Work with the managed T3 Code service, pairing, Git, and HTTPS endpoints on an infra-tools VM.
metadata:
  managed-by: infra_tools
---

# Managed T3 Code workflow

Treat the VM as the source of truth for projects, Git credentials, provider
sessions, and the T3 Code service. Do not copy pairing tokens or credentials
into prompts, repositories, logs, or generated files.

## Check readiness

Run the target-user diagnostic before changing service configuration:

```bash
infra-tools agent doctor --capability t3code
```

Use `--json` when another tool needs to consume the result. If the diagnostic
offers a safe repair, use:

```bash
infra-tools agent doctor --capability t3code --fix
```

## Pair a client

From the control system, obtain a fresh one-time administrative link:

```bash
infra-tools agent web pair HOST USER
```

Use the complete URL in the T3 desktop, mobile, or browser client. A bare T3
address is expected to show a pairing-key form. Treat pairing URLs as secrets.

Prefer an HTTPS or private-tailnet endpoint for browser-hosted clients. For a
loopback service, use the managed gateway rather than binding T3 publicly:

```bash
sudo infra-web forward add t3code --listen auto --to 127.0.0.1:3773
```

## Source control

Authentication runs on the VM. Use the GitHub CLI and HTTPS repository URLs
when adding projects. Check Git identity and credentials with the diagnostic;
never place tokens in a remote URL or commit them to a project.

## Service operations

The managed service is `infra-tools-t3code.service`. Inspect failures with:

```bash
sudo systemctl status infra-tools-t3code.service
sudo journalctl -u infra-tools-t3code.service -n 100 --no-pager
```

Keep the T3 runtime and wrapper managed by infra-tools. Do not use `npx` to
replace it or install a second T3 runtime in the workspace.
