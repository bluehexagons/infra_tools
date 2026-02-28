# AI Agent Quick Start

## Essential Pattern

```python
from __future__ import annotations
from lib.types import JSONDict, StrList
from lib.config import SetupConfig
from lib.machine_state import is_container, can_modify_kernel

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
| Machine State | `lib/machine_state.py` | `is_container`, `can_modify_kernel` |
| Validation | `lib/validation.py` | `validate_path` |
| SSH | `lib/remote_utils.py` | `run_command` |

## Quick Commands

```bash
python3 -m py_compile file.py
python3 setup_server_web.py test.com --dry-run
python3 -m pytest tests/ -v
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
