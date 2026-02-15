#!/usr/bin/env python3
"""Server-side state persistence for machine configuration."""

from __future__ import annotations

import json
import os
from typing import Optional, Any

from lib.config import DEFAULT_MACHINE_TYPE, MACHINE_TYPES, SYSTEM_TYPES


STATE_DIR = "/opt/infra_tools/state"

# Required keys for each state file
_MACHINE_STATE_REQUIRED_KEYS = ("machine_type", "system_type", "username")
_SETUP_CONFIG_REQUIRED_KEYS = ("host", "username", "system_type")
STATE_FILE = os.path.join(STATE_DIR, "machine.json")
SETUP_CONFIG_FILE = os.path.join(STATE_DIR, "setup.json")


def save_machine_state(
    machine_type: str,
    system_type: str,
    username: str,
    extra_data: Optional[dict[str, Any]] = None
) -> None:
    """Save machine state to the target system."""
    os.makedirs(STATE_DIR, exist_ok=True)
    
    state: dict[str, Any] = {
        "machine_type": machine_type,
        "system_type": system_type,
        "username": username,
    }
    
    if extra_data:
        state.update(extra_data)
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def _default_machine_state() -> dict[str, Any]:
    """Return the default machine state used when no valid state is available."""
    return {
        "machine_type": DEFAULT_MACHINE_TYPE,
        "system_type": None,
        "username": None,
    }


def _validate_machine_state(state: Any) -> Optional[str]:
    """Validate machine state structure.

    Returns None if valid, or an error message string if invalid.
    """
    if not isinstance(state, dict):
        return f"Expected dict, got {type(state).__name__}"

    missing = [k for k in _MACHINE_STATE_REQUIRED_KEYS if k not in state]
    if missing:
        return f"Missing required keys: {', '.join(missing)}"

    machine_type = state["machine_type"]
    if machine_type is not None and machine_type not in MACHINE_TYPES:
        return f"Unknown machine_type: {machine_type!r}"

    return None


def load_machine_state() -> dict[str, Any]:
    """Load machine state from the target system."""
    if not os.path.exists(STATE_FILE):
        return _default_machine_state()

    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load machine state: {e}")
        return _default_machine_state()

    error = _validate_machine_state(state)
    if error:
        print(f"Warning: Invalid machine state ({error}), using defaults")
        return _default_machine_state()

    return state


def get_machine_type() -> str:
    """Get the machine type from stored state."""
    state = load_machine_state()
    return state.get("machine_type", DEFAULT_MACHINE_TYPE)


def is_unprivileged() -> bool:
    """Check if running in an unprivileged LXC container."""
    return get_machine_type() == "unprivileged"


def is_oci() -> bool:
    """Check if running in an OCI container (Docker, Podman)."""
    return get_machine_type() == "oci"


def is_container() -> bool:
    """Check if running in any container type."""
    return get_machine_type() in ("unprivileged", "oci")


def is_vm() -> bool:
    """Check if running in a virtual machine."""
    return get_machine_type() == "vm"


def is_privileged_container() -> bool:
    """Check if running in a privileged container."""
    return get_machine_type() == "privileged"


def is_hardware() -> bool:
    """Check if running on bare metal hardware."""
    return get_machine_type() == "hardware"


def has_gpu_access() -> bool:
    """Check if GPU/DRI access is available."""
    return get_machine_type() in ("vm", "privileged", "hardware")


def can_modify_kernel() -> bool:
    """Check if kernel parameters can be modified."""
    return get_machine_type() in ("vm", "privileged", "hardware")


def can_manage_firewall() -> bool:
    """Check if firewall can be managed."""
    return get_machine_type() in ("vm", "privileged", "hardware")


def can_manage_swap() -> bool:
    """Check if swap can be configured."""
    return get_machine_type() in ("vm", "privileged", "hardware")


def can_manage_time_sync() -> bool:
    """Check if time synchronization can be configured."""
    return get_machine_type() in ("vm", "privileged", "hardware")


def can_restart_system() -> bool:
    """Check if system restart is possible.
    
    LXC containers can restart themselves. OCI containers cannot.
    """
    return get_machine_type() != "oci"


def save_setup_config(config_dict: dict[str, Any]) -> None:
    """Save the setup configuration to the target system for later recall."""
    os.makedirs(STATE_DIR, exist_ok=True)
    
    with open(SETUP_CONFIG_FILE, 'w') as f:
        json.dump(config_dict, f, indent=2)


def _validate_setup_config(config: Any) -> Optional[str]:
    """Validate setup config structure.

    Returns None if valid, or an error message string if invalid.
    """
    if not isinstance(config, dict):
        return f"Expected dict, got {type(config).__name__}"

    missing = [k for k in _SETUP_CONFIG_REQUIRED_KEYS if k not in config]
    if missing:
        return f"Missing required keys: {', '.join(missing)}"

    system_type = config.get("system_type")
    if system_type is not None and system_type not in SYSTEM_TYPES:
        return f"Unknown system_type: {system_type!r}"

    machine_type = config.get("machine_type")
    if machine_type is not None and machine_type not in MACHINE_TYPES:
        return f"Unknown machine_type: {machine_type!r}"

    return None


def load_setup_config() -> Optional[dict[str, Any]]:
    """Load the setup configuration from the target system."""
    if not os.path.exists(SETUP_CONFIG_FILE):
        return None
    
    try:
        with open(SETUP_CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load setup configuration: {e}")
        return None

    error = _validate_setup_config(config)
    if error:
        print(f"Warning: Invalid setup configuration ({error})")
        return None

    return config
