# Quick Reference

## 🎯 Essential Type Aliases

```python
# Import these first!
from lib.types import (
    JSONDict,      # dict[str, Any] - JSON-like objects
    StrList,       # list[str] - String lists  
    MaybeStr,      # Optional[str] - Optional strings
    StepFunc,      # Callable[..., Any] - Step functions
    PathPair,      # tuple[str, str] - Source/destination paths
)
```

## 📁 Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Types | `lib/types.py` |
| SSH Operations | `lib/remote_utils.py` |
| Validation | `lib/validators.py` |
| Setup Steps | `lib/*_steps.py` |
| Entry Points | `setup_*.py` |
| Arguments | `lib/arg_parser.py` |

## 🔧 Function Template

```python
def function_name(config: SetupConfig, data: JSONDict) -> MaybeStr:
    """Return error message if invalid, None if valid."""
    if already_configured():
        print("  ✓ Feature already configured")
        return None
    
    # Implementation
    return None
```

## ⚡ Quick Commands

```bash
# Check syntax
python3 -m py_compile file.py

# Dry run test
python3 setup_server_web.py test.example.com --dry-run

# Search patterns
grep -r "pattern" lib/
```

## 🚨 Critical Rules

- **Always** use `from __future__ import annotations`
- **Never** commit secrets or credentials
- **Always** validate inputs with `lib/validators.py`
- **Never** break existing function signatures without updating all references
- **Always** read complete file before changing