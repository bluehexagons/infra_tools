# AI Agent Instructions

⚡ **Quick guidance for AI agents working on this Python 3.9+ Linux automation project.**

## 🚀 4-Step Workflow

1. **Read the target file completely** before making changes
2. **Use type aliases from `lib/types.py`** (import first!)  
3. **Follow existing patterns** in the file you're editing
4. **Test with `python3 -m py_compile <file>`**

## 🎯 Essential Pattern

```python
from __future__ import annotations
from typing import Optional, Any
from lib.types import JSONDict, MaybeStr
from lib.config import SetupConfig
from lib.machine_state import is_container, can_modify_kernel

def setup_feature(config: SetupConfig) -> None:
    """Standard setup step."""
    if not can_modify_kernel():
        print("  ✓ Skipping feature (not supported in containers)")
        return
    
    if is_already_configured():
        print("  ✓ Feature already configured")
        return
    
    # Implementation here
    print("  ✓ Feature configured")
```

## 📁 Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| SSH Operations | `lib/remote_utils.py` |
| Validation | `lib/validators.py` |
| Setup Steps | `common/`, `desktop/`, `security/`, `web/`, `smb/`, `sync/`, `deploy/` |

## 📂 Directory Structure

```
/lib              - Core libraries (config, types, utilities)
/common           - User setup, packages, swap, CLI tools
/desktop          - XRDP, desktop environments, apps
/security         - Firewall, SSH, fail2ban, kernel hardening
/web              - Nginx, SSL, deployments
/smb              - Samba server and client
/sync             - Rsync and par2 data integrity
/deploy           - Rails/Node/static deployment
```

## ⚠️ 5 Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with `lib/validators.py`
4. **Never** break existing function signatures without updating all references
5. **Always** read complete file before changing

## 🖥️ Machine Type Awareness

Setup adapts to environment type via `lib/machine_state.py`:

```python
from lib.machine_state import is_container, can_modify_kernel, can_manage_swap

# Skip features not supported in containers
if not can_manage_swap():
    print("  ✓ Skipping (host-managed)")
    return
```

**Machine types:** `unprivileged` (LXC, default), `vm`, `privileged`, `hardware`, `oci` (Docker/Podman)

See `docs/MACHINE_TYPES.md` for capability matrix.

## 🔧 Common Tasks

| Task | Steps |
|------|-------|
| **Add Setup Step** | 1. Function in `module/*_steps.py` → 2. Add to setup script |
| **Modify Config** | 1. Update `SetupConfig` in `lib/config.py` → 2. Update `lib/arg_parser.py` |
| **Fix Bug** | 1. Preserve signatures → 2. Follow error patterns → 3. Test compile |
| **Add Machine Check** | 1. Use `lib/machine_state.py` helpers → 2. Skip or adapt gracefully |

## 🧪 Quick Test

```bash
python3 -m py_compile lib/modified_file.py
python3 setup_server_web.py test.example.com --dry-run
```

---

📖 **See `QUICK_REFERENCE.md` for detailed type aliases and patterns**

**Project: Automated Linux server/workstation setup via SSH with security hardening. Stability, security, and maintainability are priorities.**