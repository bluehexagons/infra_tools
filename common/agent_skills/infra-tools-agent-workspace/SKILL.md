---
name: infra-tools-agent-workspace
description: Use when concurrent coding tasks need isolated Git branches and worktrees on an infra-tools agent VM.
metadata:
  managed-by: infra_tools
---

# Managed agent workspaces

Use the managed workspace command before concurrent tasks could edit the same
checkout. It creates a dedicated `agent/TASK` branch below the user's private
infra-tools worktree root and never modifies the primary checkout's files.

## Create and inspect

From any location, supply the primary repository and a short task name:

```bash
infra-tools agent workspace create ~/repos/PROJECT TASK --base HEAD --json
infra-tools agent workspace list ~/repos/PROJECT --json
infra-tools agent workspace status WORKTREE --json
```

Use the returned absolute worktree path as the task's working directory. Use a
different task name for every concurrent task. Do not create ad hoc sibling
clones or run multiple editing agents in the primary checkout.

The default base is the primary checkout's current `HEAD`. Supply a specific
verified branch or commit with `--base` when the task must start elsewhere.

## Cleanup

Inspect first, then preview the removal:

```bash
infra-tools agent workspace status WORKTREE --json
infra-tools agent workspace remove WORKTREE --dry-run --json
infra-tools agent workspace remove WORKTREE --json
```

Removal is intentionally narrow. It refuses the primary checkout, paths
outside the managed workspace root, non-`agent/*` branches, dirty or untracked
files, and branches that are not merged into the primary checkout's current
`HEAD`. Resolve those conditions explicitly; never bypass them with `git
worktree remove --force` or `git branch -D` unless the user separately asks to
discard work.
