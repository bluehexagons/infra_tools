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
| Bootstrap | `lib/orchestrator_bootstrap.py`, `install.sh` |

## Validation

- Use `lib.validation` for filesystem paths, package names, network values,
  setup configuration, and other structured inputs.
- Use `lib.validators` for hostnames, IP addresses, and usernames.
- Validate at the CLI or setup boundary before invoking remote or system
  mutations.

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
from __future__ import annotations

from lib.config import SetupConfig
from lib.machine_state import can_modify_kernel

def setup_kernel_feature(config: SetupConfig) -> None:
    del config
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

## Quick Commands

```bash
python3 -m py_compile file.py
python3 infra_tools.py setup server_web test.com --dry-run
python3 -m unittest discover -s tests
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

## Setup composition

Setup types are registered by `PluginDefinition` objects in `plugins/`.
Composition plugins expose `step_builder` functions; capability plugins expose
shared step extensions or custom steps. Prefer extending the owning plugin
builder over adding a second dispatch path.
