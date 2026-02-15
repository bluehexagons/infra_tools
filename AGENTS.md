# AI Agent Instructions

This file provides quick guidance for AI agents working on the infra_tools project.

## 📖 Documentation

Full agent documentation is located in `.github/ai-agents/`:

- **[README.md](.github/ai-agents/README.md)** - Core instructions, workflow, testing guidelines
- **[QUICK_REFERENCE.md](.github/ai-agents/QUICK_REFERENCE.md)** - Type aliases, patterns, code templates
- **[index.md](.github/ai-agents/index.md)** - Documentation index and navigation

## 🚀 Quick Start

```python
from __future__ import annotations
from lib.types import JSONDict, StrList
from lib.config import SetupConfig
from lib.runtime_config import RuntimeConfig
from lib.machine_state import is_container, can_modify_kernel

def setup_feature(config: SetupConfig) -> None:
    """Standard setup step with machine type awareness."""
    if not can_modify_kernel():
        print("  ✓ Skipping (container)")
        return
    # Implementation
```

**Runtime vs Setup Config:**
- Use `SetupConfig` for initial setup and CLI parsing
- Use `RuntimeConfig` for service tools and periodic operations

## ⚠️ Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with `lib/validation.py`
4. **Never** break function signatures without updating all callers
5. **Always** read complete file before changing
6. **Always** keep docs up to date when changing patterns
7. **Always** remove unused code — don't keep for "API compatibility"

## 🧪 Testing

```bash
# Run all tests
python3 -m pytest tests/ -v

# Compile check
python3 -m py_compile file.py
```

## 📂 Project Structure

```
/lib          - Core libraries
/sync         - Storage operations (rsync, par2)
/common       - User setup, packages
/desktop      - XRDP, desktop environments
/security     - Firewall, SSH hardening
/web          - Nginx, SSL, deployments
/smb          - Samba server and client
/tests        - Unit tests
/docs         - Architecture documentation
```

---

**See `.github/ai-agents/` for complete documentation.**
