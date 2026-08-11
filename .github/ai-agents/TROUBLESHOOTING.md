# AI Agent Troubleshooting

## Common Issues

| Issue | Solution |
|-------|----------|
| Import errors | Run from the repo root or use the package import paths under `lib/` |
| Permission denied | Check the capability relevant to the operation (`can_modify_kernel`, `can_manage_firewall`, `can_manage_swap`, or `can_restart_system`) and verify the command's privilege boundary |
| Test modifications | Mock system calls with `unittest.mock`, use `tempfile.TemporaryDirectory()` |
| Unexpected diff | Run `git status -sb`, preserve unrelated changes, and inspect `git diff` before staging |
| Setup changes the wrong machine | Use `--dry-run`; remember `remote_setup.py` mutates the target while `bootstrap`/`self-setup` mutates the local orchestration host |

## Edit Tool Errors

- **oldString not found**: Read file first, include more context, match exact indentation
- **Found multiple matches**: Provide more surrounding context or use `replaceAll=True`

## Debugging Tips

```python
from lib.machine_state import is_container, can_modify_kernel
print(f"container={is_container()}, can_modify_kernel={can_modify_kernel()}")
```

Use the operation-specific helpers in `lib.machine_state` rather than treating
all containers as unable to run every setup step. For input failures, inspect
`lib.validation` and `lib.validators` before changing the command path.

## Resources

- Patterns: QUICK_START.md, QUICK_REFERENCE.md
- Testing: README.md
- Machine types: docs/MACHINE_TYPES.md
