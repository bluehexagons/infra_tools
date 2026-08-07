# AI Agent Quick Start

## Essential Pattern

```python
from __future__ import annotations
from lib.types import JSONDict, StrList
from lib.config import SetupConfig
from lib.machine_state import can_modify_kernel

def setup_feature(config: SetupConfig) -> None:
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## Key Files

| Purpose | File | Import |
|---------|------|--------|
| Configuration | `lib/config.py` | `SetupConfig` |
| Types | `lib/types.py` | `JSONDict`, `StrList` |
| Machine State | `lib/machine_state.py` | `can_modify_kernel` |
| Validation | `lib/validation.py` | `validate_path` |
| SSH | `lib/remote_utils.py` | `run` |

## Quick Commands

```bash
python3 -m py_compile file.py
python3 infra_tools.py setup server_web test.com --dry-run
python3 -m unittest discover -s tests
```

## Critical Rules

1. Use `from __future__ import annotations`
2. Never commit secrets
3. Validate inputs with `lib/validation.py`
4. Read complete file before changing
5. Check machine type capabilities
6. Keep docs up to date
7. Remove unused code

## Testing

- Tests use `unittest` in `tests/`
- Must not modify local system
- Mock system calls, use `tempfile.TemporaryDirectory()`

---

See README.md for full guidelines.
