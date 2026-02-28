# AI Agent Troubleshooting

## Common Issues

| Issue | Solution |
|-------|----------|
| Import errors | Add `sys.path.insert(0, '../lib')` at top of file |
| Permission denied | Use `can_modify_kernel()` check before system operations |
| Test modifications | Mock system calls with `unittest.mock`, use `tempfile.TemporaryDirectory()` |

## Edit Tool Errors

- **oldString not found**: Read file first, include more context, match exact indentation
- **Found multiple matches**: Provide more surrounding context or use `replaceAll=True`

## Debugging Tips

```python
from lib.machine_state import is_container, can_modify_kernel
print(f"container={is_container()}, can_modify_kernel={can_modify_kernel()}")
```

## Resources

- Patterns: QUICK_START.md, QUICK_REFERENCE.md
- Testing: README.md
- Machine types: docs/MACHINE_TYPES.md
