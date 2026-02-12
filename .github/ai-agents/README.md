# AI Agent Instructions

⚡ **Quick guidance for AI agents working on this Python 3.9+ Linux automation project.**

## 🚀 4-Step Workflow

1. **Read the target file completely** before making changes
2. **Use type aliases from `lib/types.py`** (import first!)  
3. **Follow existing patterns** in the file you're editing
4. **Test with `python3 -m py_compile <file>`** and run unit tests

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
| Validation | `lib/validators.py`, `lib/validation.py` |
| Task Utilities | `lib/task_utils.py` |
| Setup Steps | `common/`, `desktop/`, `security/`, `web/`, `smb/`, `sync/`, `deploy/` |
| Tests | `tests/test_storage.py`, `tests/test_xrdp.py` |
| Docs | `docs/STORAGE.md`, `docs/LOGGING.md`, `docs/MACHINE_TYPES.md`, `docs/XRDP.md` |

## 📂 Directory Structure

```
/lib              - Core libraries (config, types, utilities, validation)
/common           - User setup, packages, swap, CLI tools
/desktop          - XRDP, desktop environments, apps
/security         - Firewall, SSH, fail2ban, kernel hardening
/web              - Nginx, SSL, deployments
/smb              - Samba server and client
/sync             - Rsync and par2 data integrity
/deploy           - Rails/Node/static deployment
/tests            - Unit tests (run on Debian, no system changes)
/docs             - Architecture and usage documentation
```

## ⚠️ Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with `lib/validators.py` or `lib/validation.py`
4. **Never** break existing function signatures without updating all callers and tests
5. **Always** read complete file before changing
6. **Always** keep agent instructions (`/.github/ai-agents/`) and docs (`/docs/`) up to date when making changes — document new patterns, challenges, and design decisions
7. **Always** remove unused/deprecated parameters and code — API compatibility is not a concern

## 🧪 Testing

Tests are in `tests/` using `unittest` (not pytest fixtures). They are intended to run on a Debian system and **must not make any changes to the local system** (no installs, no writes outside of temp directories, no network calls).

### Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run a specific test class
python3 -m pytest tests/test_storage.py::TestParseSyncSpec -v

# Compile check (quick validation)
python3 -m py_compile lib/modified_file.py
```

### Writing Tests

- **Optimize for code coverage** — test all code paths, including error cases and boundary values
- **Avoid redundancy** — one test per behavior; don't test the same code path twice
- **Catch regressions** — assert return values (not just "doesn't raise"), test that functions used in boolean context return the expected type
- **Mock system calls** — use `unittest.mock` or direct function replacement to avoid real `chown`, `systemctl`, etc.
- **Use `tempfile.TemporaryDirectory()`** for filesystem tests — never write to fixed paths
- **Import modules at top level** — avoid repeated `import` inside test methods

### Known Testing Challenges

- **`lib/remote_utils.run`** executes via `subprocess.run(shell=True)` and does not raise on non-zero exit; `check` only controls warning printing. Tests that mock `run` must return appropriate `CompletedProcess` objects.
- **Validation functions used in boolean context** — if a validation function is called with `if not validate_foo(...)`, it must explicitly return `True` on success (not `None`). Test the return value, not just the absence of exceptions.
- **Unused function parameters** — remove them rather than keeping for "API compatibility". Update all callers and tests.
- **Duplicate logic** — watch for copy-pasted blocks across step modules (e.g., directory creation). Extract to shared helpers in `lib/task_utils.py`.
- **String-based checks** — be wary of `if "text" in variable` where `variable` might be a filename rather than file contents. Verify the variable actually holds what you expect.

### Known XRDP Issues

**Session freezing on window resize** is a persistent issue with xrdp/xorgxrdp dynamic resolution:
- **Root causes**: Race conditions in xorgxrdp driver, XFCE desktop environment conflicts with RANDR, X server state issues
- **Mitigations implemented**: Xwrapper.config for permissions, XFCE RDP compatibility tweaks (disable light-locker, DPMS), simplified session startup, optimized TCP buffers
- **Current status**: Freezing reduced but not eliminated; disconnect/reconnect often resolves temporarily
- **Debugging**: See `docs/XRDP.md` for comprehensive troubleshooting guide including log locations, test procedures, and known workarounds
- **Tests**: `tests/test_xrdp.py` covers configuration generation and file creation, but cannot test runtime behavior

For XRDP issues, refer users to `docs/XRDP.md` which includes diagnostic checklists, log analysis, and upstream issue tracking.

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
| **Add Setup Step** | 1. Function in `module/*_steps.py` → 2. Add to setup script → 3. Add tests |
| **Modify Config** | 1. Update `SetupConfig` in `lib/config.py` → 2. Update `lib/arg_parser.py` |
| **Fix Bug** | 1. Preserve signatures → 2. Follow error patterns → 3. Add regression test |
| **Add Machine Check** | 1. Use `lib/machine_state.py` helpers → 2. Skip or adapt gracefully |
| **Update Docs** | 1. Update relevant `docs/*.md` → 2. Update agent instructions if patterns changed |

---

📖 **See `QUICK_REFERENCE.md` for detailed type aliases and patterns**

**Project: Automated Linux server/workstation setup via SSH with security hardening. Stability, security, and maintainability are priorities.**