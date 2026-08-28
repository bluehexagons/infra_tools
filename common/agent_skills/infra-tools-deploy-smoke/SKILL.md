---
name: infra-tools-deploy-smoke
description: Prepare and verify a test deployment from an infra-tools-managed coding VM.
metadata:
  managed-by: infra_tools
---

# Deployment smoke checks

Use this workflow after the application and infra-tools test suites pass and
before declaring a test deployment ready.

## Preflight

Keep application and infrastructure changes in their own repositories and
confirm both checkouts are clean except for the intended commits:

```bash
git status --short --branch
git log -1 --oneline
infra-tools agent doctor --capability host --json
```

Check `--capability t3code` separately when the deployment workflow actually
depends on the managed T3 service. Do not make T3 readiness a prerequisite for
an SSH-only agent VM.

Inspect the application's deployment manifest and the saved infra-tools setup
before mutation. Use the repository's documented test command and deployment
command; do not invent production secrets, hostnames, or database paths. Run a
dry run when the selected infra-tools command provides one.

## Verify the deployed service

Check the service manager, loopback health endpoint, and public HTTPS endpoint
as separate layers. Prefer T3 Code's collaborative preview for browser checks.
If the session is SSH-only and the VM was explicitly provisioned with
`--browser-automation playwright`, first run:

```bash
infra-tools agent doctor --capability browser
```

Capture the deployed commit identifier, HTTP status, and a small set of
user-visible smoke interactions. Never dump response bodies that may contain
credentials or private user data. For a live development preview, use the
`infra-tools-web-gateway` skill instead of opening a direct firewall port.

## Failure handoff

On failure, preserve the last known-good release and collect:

```bash
infra-tools agent support-bundle --output ~/agent-support.json
```

Add only bounded service logs relevant to the failed deployment after
reviewing them for secrets. Do not reset a dirty checkout, delete an unmerged
worktree, rotate credentials, or retry a stateful migration destructively
without explicit authorization.
