---
name: infra-tools-agent-operations
description: Check or deliberately update coding agents, rotate their credentials, or protect long work from host maintenance on an infra-tools agent VM.
metadata:
  managed-by: infra_tools
---

# Agent VM operations

Use the managed commands so checks, updates, and handoffs stay bounded and
redacted.

## Readiness and updates

Check host health and only the tools the VM is expected to provide:

```bash
infra-tools agent doctor --capability host --json
infra-tools agent doctor --capability development --json
infra-tools agent doctor --tool codex --json
infra-tools agent doctor --all-capabilities --json
```

The comprehensive check inventories every default terminal client but requires
only those currently installed. Use explicit `--tool` flags when an absent
client should make readiness fail; each selected tool is then required.
The development capability inventories Godot, Go, and Node independently, so
an unselected toolchain is informational while a broken installed baseline is
unhealthy.

Preview terminal-agent updates before applying them as the account that owns
the installation. Apply an update only when the user requested it:

```bash
infra-tools agent update --dry-run
infra-tools agent update --tool codex
infra-tools agent doctor --last-record --json
```

`agent update` manages Codex, Claude Code, and OpenCode. It does not update
GitHub CLI, T3 Code, infra-tools itself, or system packages. Do not substitute a
vendor updater unless the user requests it; the managed path verifies the tool,
retains one prior executable, rolls back a broken update, and records redacted
post-update readiness.

From a control system, add `HOST USER` to `doctor` or `update`. Run the remote
dry run first.

## Maintenance holds

Create a hold only when work must cross the normal restart window:

```bash
infra-tools agent maintenance hold --hours 8
infra-tools agent maintenance status --json
infra-tools agent maintenance release
```

Release it when the protected work ends. Holds expire after at most 72 hours
and do not override the host's forced-restart deadline.

## Credential rotation

Credential status and replacement run from the control system:

```bash
infra-tools agent auth status HOST USER --json
infra-tools agent auth set HOST USER --tool codex --interactive
```

Inspect status first and replace a credential only when explicitly requested.
Use `--active` or a protected controller-local `--file` when appropriate.
Never print credential files or place them in a repository. Ordinary setup is
preserve-first, but may replace refresh-required Codex auth from an
unambiguously current staged source. `auth set` intentionally replaces the
selected target credential in every other rotation case.
