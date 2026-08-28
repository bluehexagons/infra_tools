---
name: infra-tools-vm-triage
description: Diagnose an infra-tools agent VM that is slow, unhealthy, low on capacity, or needs a shareable support snapshot.
metadata:
  managed-by: infra_tools
---

# Agent VM triage

Start with stable, non-secret diagnostics:

```bash
infra-tools agent doctor --capability host --json
```

Add `--capability t3code` when the VM was provisioned for T3 Code. Add explicit
`--tool` checks for the coding agents involved in the failure; the default tool
set may include tools that were intentionally not installed.

Interpret T3 service readiness separately from host warnings. Host warnings
cover memory, swap, disk headroom, bounded agent storage, maintenance timers,
and pending reboots. Only critical disk pressure or failed maintenance makes
the host capability unhealthy.

If the service is unhealthy, inspect its user unit and bounded recent output:

```bash
systemctl --user status t3code.service --no-pager
journalctl --user -u t3code.service -n 100 --no-pager
```

Use `infra-tools agent doctor --capability t3code --fix` only for its documented
safe repairs: GitHub's Git credential helper, an incomplete T3 native runtime,
or an inactive managed T3 service.

## Support snapshot

Print a redacted JSON snapshot:

```bash
infra-tools agent support-bundle
```

Or save a new private file below the current user's home:

```bash
infra-tools agent support-bundle --output ~/agent-support.json
```

The snapshot inventories optional browser configuration without launching a
browser. Add `--browser-smoke` only when Playwright was explicitly installed
and reproducing browser startup is relevant.

The snapshot contains tool versions, Boolean credential health, stable doctor
results, service resource counters, maintenance state, and aggregate T3 log
metadata. It omits credential contents, log contents, repository contents,
changed file names, prompts, sessions, Git identity, and user-home paths.
Review the JSON before sharing it. Do not attach raw agent credentials or
session files as supplemental evidence.
