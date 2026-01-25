#!/usr/bin/env python3
"""Server-side state persistence for machine configuration."""

from __future__ import annotations

import json
import os
from typing import Optional, Any

from lib.config import DEFAULT_MACHINE_TYPE


STATE_DIR = "/opt/infra_tools/state"
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


def load_machine_state() -> dict[str, Any]:
    """Load machine state from the target system."""
    if not os.path.exists(STATE_FILE):
        return {
            "machine_type": DEFAULT_MACHINE_TYPE,
            "system_type": None,
            "username": None,
        }
    
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load machine state: {e}")
        return {
            "machine_type": DEFAULT_MACHINE_TYPE,
            "system_type": None,
            "username": None,
        }


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


def load_setup_config() -> Optional[dict[str, Any]]:
    """Load the setup configuration from the target system."""
    if not os.path.exists(SETUP_CONFIG_FILE):
        return None
    
    try:
        with open(SETUP_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load setup configuration: {e}")
        return None
