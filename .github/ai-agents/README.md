# AI Agent Instructions

Quick guidance for AI agents. See **QUICK_START.md** for the essentials.

## 4-Step Workflow

1. **Read the target file completely** before making changes
2. **Use existing type aliases from `lib/types.py`** when they match the data;
   do not add duplicate aliases or imports that are not needed
3. **Follow existing patterns** in the file you're editing
4. **Test with `python3 -m py_compile <file>`** and run unit tests

Before editing, run `git status -sb`. Preserve unrelated changes, use
`apply_patch`, and review `git diff --check` plus the final diff before staging.

## Critical Rules

1. **Always** use `from __future__ import annotations`
2. **Never** commit secrets or credentials
3. **Always** validate inputs with the right module: `lib.validation` handles
   structured paths, packages, network, and setup values; `lib.validators`
   handles hosts, IPs, and usernames.
4. **Never** break function signatures without updating all callers/tests
5. **Always** read complete file before changing
6. **Always** keep docs up to date when changing patterns
7. **Always** remove unused/deprecated code — API compatibility is not a concern
8. **Always** choose the matching machine capability helper; do not use
   `can_modify_kernel()` as a generic package/service guard

## Testing

```bash
python3 -m unittest discover -s tests
python3 -m py_compile file.py
```

- Tests use `unittest`, run on Debian, **must not modify local system**
- Mock system calls with `unittest.mock`
- Use `tempfile.TemporaryDirectory()` for filesystem tests
- Use setup `--dry-run` for plan validation and never run tests against a real
  target system

## Machine Type Awareness

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

**Types:** `auto` (default), `unprivileged` (LXC), `vm`, `hardware`, plus the
explicit compatibility labels `privileged` and `oci` (Docker/Podman). Official
support targets Debian bare metal, Debian VMs, and unprivileged Debian LXC on
Proxmox.

See `docs/MACHINE_TYPES.md` for capability matrix.

## Setup boundaries and composition

`infra_tools setup` validates configuration and delegates target-side work to
`remote_setup.py`. The target step list comes from the plugin registry and
`plugins/*` step builders. `bootstrap`/`self-setup` is the local orchestration
host flow implemented in `lib/orchestrator_bootstrap.py`; `install.sh` invokes
that flow before any requested local setup.

## Key Files

| Purpose | File |
|---------|------|
| Configuration | `lib/config.py` |
| Runtime configuration | `lib/runtime_config.py` |
| Types | `lib/types.py` |
| Machine State | `lib/machine_state.py` |
| Validation | `lib/validation.py` |
| SSH Operations | `lib/remote_utils.py` |

## Common Tasks

| Task | Steps |
|------|-------|
| Add Setup Step | Add the function to its owning package → wire the relevant `plugins/*` builder or capability extension → add focused tests and docs |
| Modify Config | Update `SetupConfig` in `lib/config.py` → Update `lib/arg_parser.py` |
| Fix Bug | Preserve signatures → Follow error patterns → Add regression test |

---

**QUICK_START.md** has the essential pattern and quick commands
