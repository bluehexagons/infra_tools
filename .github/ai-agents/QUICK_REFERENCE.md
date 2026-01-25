# Quick Reference

## 🎯 Essential Type Aliases

```python
# Import these first!
from lib.types import (
    JSONDict,      # dict[str, Any]
    StrList,       # list[str]
    MaybeStr,      # Optional[str]
    StepFunc,      # Callable[..., Any]
    PathPair,      # tuple[str, str]
)
```

## 📁 Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| SSH Operations | `lib/remote_utils.py` |
| Validation | `lib/validators.py` |
| Arguments | `lib/arg_parser.py` |
| Setup Steps | Module directories: `common/`, `desktop/`, `security/`, `web/`, `smb/`, `sync/`, `deploy/` |
| Entry Points | `setup_*.py`, `patch_setup.py`, `remote_setup.py` |

## 🖥️ Machine Type Helpers

```python
from lib.machine_state import (
    is_container,           # True for unprivileged/oci
    is_unprivileged,        # True for unprivileged LXC
    is_oci,                 # True for Docker/Podman
    is_vm,                  # True for VMs
    is_privileged_container, # True for privileged LXC
    is_hardware,            # True for bare metal
    has_gpu_access,         # Can use GPU/DRI
    can_modify_kernel,      # Can use sysctl
    can_manage_firewall,    # Can configure UFW
    can_manage_swap,        # Can configure swap
    can_manage_time_sync,   # Can configure chrony
    can_restart_system,     # Can restart (False for oci)
)
```

## 🔧 Function Templates

### Setup Step
```python
def setup_feature(config: SetupConfig) -> None:
    """Setup step with machine type awareness."""
    if not can_modify_kernel():
        print("  ✓ Skipping (not supported in containers)")
        return
    
    if already_configured():
        print("  ✓ Feature already configured")
        return
    
    # Implementation
    print("  ✓ Feature configured")
```

### Validation
```python
def validate_input(value: str) -> MaybeStr:
    """Return error message if invalid, None if valid."""
    if not value:
        return "Value is required"
    if len(value) < 3:
        return "Value must be at least 3 characters"
    return None
```

## ⚡ Quick Commands

```bash
# Check syntax
python3 -m py_compile file.py

# Dry run test
python3 setup_server_web.py test.example.com --dry-run

# Search patterns
grep -r "pattern" lib/ common/ desktop/
```

## 📂 Module Organization

| Module | Purpose |
|--------|---------|
| `lib/` | Core libraries and utilities |
| `common/` | User setup, packages, swap, CLI tools, Ruby/Node/Go |
| `desktop/` | XRDP, desktop environments, browsers, apps |
| `security/` | Firewall, SSH hardening, fail2ban, kernel hardening |
| `web/` | Nginx, SSL, reverse proxy, deployments |
| `smb/` | Samba server and SMB client mounts |
| `sync/` | Rsync sync and par2 data integrity |
| `deploy/` | Rails/Node/static application deployment |

## 🚨 Critical Rules

- **Always** use `from __future__ import annotations`
- **Never** commit secrets or credentials
- **Always** validate inputs with `lib/validators.py`
- **Never** break existing function signatures without updating all references
- **Always** read complete file before changing
- **Always** check machine type capabilities for system-level operations