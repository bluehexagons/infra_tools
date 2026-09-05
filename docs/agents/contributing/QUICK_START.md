# Contributor quick start

These instructions complement the root [`AGENTS.md`](../../../AGENTS.md).
Preserve unrelated worktree changes and follow higher-priority session
instructions.

## Before editing

1. Run `git status -sb`.
2. Read the complete target file.
3. Identify the matching validator and capability helper.
4. Use `apply_patch`, then check `git diff --check`.

## Essential pattern

```python
from __future__ import annotations

from lib.config import SetupConfig
from lib.machine_state import can_modify_kernel


def setup_kernel_feature(config: SetupConfig) -> None:
    """Apply a kernel-specific setup step when supported."""
    del config
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## Quick checks

```bash
python3 -m py_compile file.py
infra-tools setup server_web test.com --dry-run
python3 -m unittest discover -s tests
```

## Non-negotiable rules

- Use `from __future__ import annotations`.
- Never commit secrets.
- Validate inputs at the CLI or setup boundary.
- Mock system calls; use `tempfile.TemporaryDirectory()` for test storage.
- Keep operator documentation current.

For helper selection and setup composition, use the
[quick reference](QUICK_REFERENCE.md). For the complete contributor workflow,
use the [contributor guide](README.md).
