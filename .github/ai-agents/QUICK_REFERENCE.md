# Quick Reference

## Type Aliases

```python
from lib.types import (
    JSONDict,      # dict[str, Any]
    StrList,       # list[str]
    MaybeStr,      # Optional[str]
    StepFunc,      # Callable[..., Any]
)
```

## Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Runtime Config | `lib/runtime_config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| Validation | `lib/validation.py` |
| Arguments | `lib/arg_parser.py` |

## Machine State Helpers

```python
from lib.machine_state import (
    is_container, is_vm, is_hardware,
    can_modify_kernel, can_manage_swap,
    can_manage_firewall, can_restart_system
)
```

## Runtime Config

- **SetupConfig** (`lib/config.py`): Initial setup, CLI parsing
- **RuntimeConfig** (`lib/runtime_config.py`): Periodic operations, service tools

## Setup Step Template

```python
def setup_feature(config: SetupConfig) -> None:
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## Quick Commands

```bash
python3 -m py_compile file.py
python3 setup_server_web.py test.com --dry-run
python3 -m pytest tests/ -v
```

## Module Organization

| Module | Purpose |
|--------|---------|
| `lib/` | Core libraries |
| `common/` | User setup, CLI tools |
| `desktop/` | XRDP, browsers |
| `security/` | Firewall, SSH |
| `web/` | Nginx, SSL |
| `smb/` | Samba |
| `sync/` | rsync, par2 |
| `deploy/` | App deployment |

See README.md for testing guidelines.
