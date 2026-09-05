# Contributor quick reference

## Types and key files

| Need | Location |
| --- | --- |
| JSON and collection aliases | `lib/types.py`: `JSONDict`, `StrList`, `MaybeStr`, `StepFunc` |
| Initial setup configuration | `lib/config.py`: `SetupConfig` |
| Periodic-operation configuration | `lib/runtime_config.py`: `RuntimeConfig` |
| CLI arguments | `lib/arg_parser.py` |
| Local bootstrap | `lib/orchestrator_bootstrap.py`, `install.sh` |

## Validation

| Input | Use |
| --- | --- |
| Paths, package names, network values, setup configuration | `lib.validation` |
| Hosts, IP addresses, usernames | `lib.validators` |

Validate before remote or system mutations.
Identity validators match the complete input, reject control-character suffixes,
and accept ASCII IPv4 digits only. Hostnames may have one terminal DNS root dot;
repeated terminal dots and names longer than 253 characters are rejected.

## Capability helpers

```python
from lib.machine_state import (
    can_manage_firewall,
    can_manage_swap,
    can_modify_kernel,
    can_restart_system,
    is_container,
    is_hardware,
    is_vm,
)
```

Use the helper for the operation, not a generic container check.

## Setup composition

`PluginDefinition` registrations in `plugins/` select setup steps. Composition
plugins own `step_builder` functions; capability plugins supply shared
extensions or custom steps. Extend the owning plugin path rather than adding a
second dispatcher.

## Repository areas

| Area | Location |
| --- | --- |
| Core libraries | `lib/` |
| User setup and CLI tools | `common/` |
| Desktop and RDP | `desktop/` |
| Firewall and SSH | `security/` |
| Nginx and TLS | `web/` |
| Samba | `smb/` |
| Rsync and par2 | `sync/` |
| Application deployment | `deploy/` |

For edit workflow and tests, see the [contributor guide](README.md).
