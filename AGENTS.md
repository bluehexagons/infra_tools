# AI Agent Quick Start

## 🚀 Essential Pattern

```python
from __future__ import annotations
from lib.types import JSONDict, StrList
from lib.config import SetupConfig
from lib.machine_state import is_container, can_modify_kernel

def setup_feature(config: SetupConfig) -> None:
    """Standard setup step with machine type awareness."""
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## ⚠️ Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with `lib/validation.py`
4. **Never** break function signatures without updating all callers
5. **Always** read complete file before changing
6. **Always** keep docs up to date when changing patterns
7. **Always** remove unused code — don't keep for "API compatibility"

## 📊 Quick Commands

```bash
# Check syntax
python3 -m py_compile file.py

# Dry run test
python3 setup_server_web.py test.com --dry-run

# Run tests
python3 -m pytest tests/ -v
```

## 📁 Key Files

| Purpose | File | Import | Key Functions |
|---------|------|--------|---------------|
| Configuration | `lib/config.py` | `SetupConfig` | `SetupConfig`, `RuntimeConfig` |
| Types | `lib/types.py` | `JSONDict`, `StrList` | `JSONDict`, `StrList`, `MaybeStr` |
| Machine State | `lib/machine_state.py` | `is_container`, `can_modify_kernel` | `is_container`, `can_modify_kernel`, `is_vm` |
| Validation | `lib/validation.py` | `validate_path` | `validate_path`, `validate_service_name` |
| SSH Operations | `lib/remote_utils.py` | `run_command` | `run_command`, `run` |

---

**See `.github/ai-agents/README.md` for detailed patterns and workflows**
