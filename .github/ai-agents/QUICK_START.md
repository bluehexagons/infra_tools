# AI Agent Quick Start

These repository-wide instructions complement the root `AGENTS.md`. Preserve
unrelated worktree changes and follow higher-priority session instructions.

## Essential Pattern

```python
from __future__ import annotations
from lib.machine_state import can_modify_kernel

def harden_kernel() -> None:
    """Apply a kernel-specific setup step when supported."""
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## Key Files

| Purpose | File | Import |
|---------|------|--------|
| Configuration | `lib/config.py` | `SetupConfig` |
| Runtime configuration | `lib/runtime_config.py` | `RuntimeConfig` |
| Types | `lib/types.py` | `JSONDict`, `StrList` |
| Machine State | `lib/machine_state.py` | `can_modify_kernel` |
| Validation | `lib/validation.py` | `validate_filesystem_path` |
| SSH | `lib/remote_utils.py` | `run` |
| Plugins | `plugins/*.py` | `PluginDefinition`, step builders |
| Self-setup | `lib/orchestrator_bootstrap.py` | `run_orchestrator_bootstrap` |

## Quick Commands

```bash
python3 -m py_compile file.py
python3 infra_tools.py setup server_web test.com --dry-run
python3 -m unittest discover -s tests
```

## Critical Rules

1. Use `from __future__ import annotations`
2. Never commit secrets
3. Validate inputs with `lib/validation.py` or `lib/validators.py`, as appropriate
4. Read complete file before changing
5. Check the capability that matches the operation
6. Keep docs up to date
7. Remove unused code
8. Run `git status -sb` first and preserve unrelated changes
9. Use `apply_patch` for edits and review `git diff --check`

## Testing

- Tests use `unittest` in `tests/`
- Must not modify local system
- Mock system calls, use `tempfile.TemporaryDirectory()`
- Use `--dry-run` for setup planning and patch external commands in unit tests

## Setup boundaries

The CLI validates setup arguments before `remote_setup.py` runs target-side
steps. `bootstrap`/`self-setup` is a separate local orchestration-host flow;
its implementation lives in `lib/orchestrator_bootstrap.py`.

---

See README.md for full guidelines.
