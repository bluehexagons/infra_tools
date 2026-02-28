# AI Agent Instructions

⚡ Quick guidance for AI agents. See **QUICK_START.md** for the essentials.

## 4-Step Workflow

1. **Read the target file completely** before making changes
2. **Use type aliases from `lib/types.py`** (import first!)
3. **Follow existing patterns** in the file you're editing
4. **Test with `python3 -m py_compile <file>`** and run unit tests

## ⚠️ Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with `lib/validation.py`
4. **Never** break function signatures without updating all callers/tests
5. **Always** read complete file before changing
6. **Always** keep docs up to date when changing patterns
7. **Always** remove unused/deprecated code — API compatibility is not a concern

## 🧪 Testing

```bash
python3 -m pytest tests/ -v
python3 -m py_compile file.py
```

- Tests use `unittest`, run on Debian, **must not modify local system**
- Mock system calls with `unittest.mock`
- Use `tempfile.TemporaryDirectory()` for filesystem tests

## 🖥️ Machine Type Awareness

```python
from lib.machine_state import can_modify_kernel, can_manage_swap

if not can_modify_kernel():
    print("  ✓ Skipping (container)")
    return
```

**Types:** `unprivileged` (LXC), `vm`, `privileged`, `hardware`, `oci` (Docker/Podman)

See `docs/MACHINE_TYPES.md` for capability matrix.

## 📁 Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| Validation | `lib/validation.py` |
| SSH Operations | `lib/remote_utils.py` |

## Common Tasks

| Task | Steps |
|------|-------|
| Add Setup Step | Function in `module/*_steps.py` → Add to setup script → Add tests |
| Modify Config | Update `SetupConfig` in `lib/config.py` → Update `lib/arg_parser.py` |
| Fix Bug | Preserve signatures → Follow error patterns → Add regression test |

---

📖 **QUICK_START.md** has the essential pattern and quick commands
