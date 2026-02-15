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
| Runtime Config | `lib/runtime_config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| SSH Operations | `lib/remote_utils.py` |
| Validation | `lib/validators.py` |
| Arguments | `lib/arg_parser.py` |
| Setup Steps | Module directories: `common/`, `desktop/`, `security/`, `web/`, `smb/`, `sync/`, `deploy/` |
| Entry Points | `setup_*.py`, `patch_setup.py`, `remote_setup.py` |

## 🔄 Runtime Configuration

Use `RuntimeConfig` for type-safe runtime operations (orchestrators, service tools):

```python
from lib.runtime_config import RuntimeConfig
from lib.machine_state import load_setup_config

# Load from JSON state at runtime
config_dict = load_setup_config()
config = RuntimeConfig.from_dict(config_dict)

# Or convert from SetupConfig
config = RuntimeConfig.from_setup_config(setup_config)

# Check operations
if config.has_storage_ops():
    paths = config.get_all_paths()
```

**When to use:**
- **SetupConfig** (`lib/config.py`): During initial setup, CLI parsing, full configuration
- **RuntimeConfig** (`lib/runtime_config.py`): During periodic operations, service tools, lightweight runtime use

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
- **Always** validate inputs with `lib/validators.py` or `lib/validation.py`
- **Never** break existing function signatures without updating all callers and tests
- **Always** read complete file before changing
- **Always** check machine type capabilities for system-level operations
- **Always** keep these agent instructions and docs up to date when changing patterns or conventions
- **Always** remove unused parameters and dead code — don't keep things for "API compatibility"

## 🧪 Testing

Tests live in `tests/` using Python `unittest`. Run with `python3 -m pytest tests/ -v`.

**Key rules:**
- Tests must run on Debian and **must not modify the local system** (no installs, no writes outside temp dirs)
- Optimize for code coverage, avoid redundant cases
- Assert return values, not just "doesn't raise"
- Mock system calls (`run`, `chown`, etc.) to avoid side effects
- Use `tempfile.TemporaryDirectory()` for filesystem tests
- Import all modules at top of file, not inside test methods

See `README.md` for known testing challenges and patterns.