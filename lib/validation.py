"""Enhanced validation framework extending existing patterns."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional, cast


def validate_filesystem_path(path: str, must_exist: bool = False, check_writable: bool = False) -> None:
    """Validate filesystem path with extended checks.
    
    Args:
        path: Path to validate
        must_exist: If True, path must exist
        check_writable: If True, path must be writable
        
    Raises:
        ValueError: If validation fails
    """
    if not path:
        raise ValueError("Path must be a non-empty string")
    
    # Basic path format validation
    try:
        Path(path)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid path format: {path}") from e
    
    if must_exist and not os.path.exists(path):
        raise ValueError(f"Path does not exist: {path}")
    
    if check_writable:
        if os.path.exists(path):
            if not os.access(path, os.W_OK):
                raise ValueError(f"Path is not writable: {path}")
        else:
            # Check parent directory for writability
            parent = os.path.dirname(path)
            if not os.path.exists(parent):
                raise ValueError(f"Parent directory does not exist: {parent}")
            if not os.access(parent, os.W_OK):
                raise ValueError(f"Parent directory is not writable: {parent}")


def validate_database_path(db_path: str) -> None:
    """Validate database path for parity file storage.
    
    The database path is a directory (e.g. .pardatabase) used to store parity
    files.  It may live inside the protected directory as a hidden subdirectory,
    which is the common usage pattern.
    
    Args:
        db_path: Database directory path to validate
        
    Raises:
        ValueError: If validation fails
    """
    # Don't require existence - database may not exist on first run
    validate_filesystem_path(db_path, must_exist=False)


def validate_service_name_uniqueness(service_name: str, existing_services: list[str]) -> bool:
    """Validate service name uniqueness and format.
    
    Args:
        service_name: Service name to validate
        existing_services: List of existing service names
        
    Returns:
        True if validation passes
        
    Raises:
        ValueError: If validation fails
    """
    if not service_name:
        raise ValueError("Service name must be a non-empty string")
    
    # Systemd unit names allow letters, digits, hyphens, underscores, and dots.
    # Max 255 chars (well within systemd limits).
    pattern = r'^[a-z_][a-z0-9_.-]{0,254}$'
    if not re.match(pattern, service_name):
        raise ValueError(f"Service name '{service_name}' must follow pattern: {pattern}")
    
    if service_name in existing_services:
        raise ValueError(f"Service name '{service_name}' already exists")
    
    # Check for systemd reserved names
    systemd_reserved = ['system', 'user', 'service', 'target', 'slice', 'scope']
    if service_name in systemd_reserved:
        raise ValueError(f"Service name '{service_name}' is reserved by systemd")
    
    return True


def validate_redundancy_percentage(redundancy: str) -> int:
    """Validate and convert redundancy percentage to integer.
    
    Args:
        redundancy: Redundancy percentage as string
        
    Returns:
        int: Validated redundancy percentage
        
    Raises:
        ValueError: If validation fails
    """
    if not redundancy:
        raise ValueError("Redundancy must be a non-empty string")
    
    # Remove % symbol if present
    redundancy_clean = redundancy.strip().rstrip('%')
    
    try:
        redundancy_int = int(redundancy_clean)
    except ValueError as e:
        raise ValueError(f"Redundancy must be a valid integer: {redundancy}") from e
    
    if not 0 <= redundancy_int <= 100:
        raise ValueError(f"Redundancy percentage must be between 0 and 100: {redundancy_int}")
    
    return redundancy_int


def validate_directory_empty(directory: str) -> None:
    """Validate that directory is empty.
    
    Args:
        directory: Directory path to check
        
    Raises:
        ValueError: If directory is not empty or doesn't exist
    """
    validate_filesystem_path(directory, must_exist=True)
    
    if not os.path.isdir(directory):
        raise ValueError(f"Path is not a directory: {directory}")
    
    try:
        entries = os.listdir(directory)
        # Skip hidden files and directories
        visible_entries = [e for e in entries if not e.startswith('.')]
        if visible_entries:
            raise ValueError(f"Directory is not empty: {directory} (contains: {', '.join(visible_entries[:5])})")
    except OSError as e:
        raise ValueError(f"Cannot read directory contents: {directory}") from e


def validate_workspace_dir(path: str) -> None:
    """Validate a workspace directory path for CLI entry points."""

    if not path:
        raise ValueError("Workspace path must be a non-empty string")

    expanded_path = os.path.abspath(os.path.expanduser(path))
    validate_filesystem_path(expanded_path, must_exist=False)

    if os.path.exists(expanded_path):
        if not os.path.isdir(expanded_path):
            raise ValueError(f"Workspace path is not a directory: {expanded_path}")
        if not os.access(expanded_path, os.W_OK):
            raise ValueError(f"Workspace path is not writable: {expanded_path}")
        return

    existing_parent = expanded_path
    while not os.path.exists(existing_parent):
        parent = os.path.dirname(existing_parent)
        if parent == existing_parent:
            break
        existing_parent = parent

    if not os.path.isdir(existing_parent):
        raise ValueError(f"Workspace parent is not a directory: {existing_parent}")
    if not os.access(existing_parent, os.W_OK):
        raise ValueError(f"Workspace parent is not writable: {existing_parent}")


def validate_network_endpoint(endpoint: str) -> None:
    """Validate network endpoint (host:port or IP:port).
    
    Args:
        endpoint: Network endpoint to validate
        
    Raises:
        ValueError: If validation fails
    """
    if not endpoint:
        raise ValueError("Endpoint must be a non-empty string")
    
    parts = endpoint.split(':')
    if len(parts) != 2:
        raise ValueError(f"Endpoint must be in format host:port: {endpoint}")
    
    host, port = parts
    
    # Validate host using existing validate_host function
    from lib.validators import validate_host
    if not validate_host(host):
        raise ValueError(f"Invalid host in endpoint: {host}")
    
    try:
        port_int = int(port)
        if not 1 <= port_int <= 65535:
            raise ValueError(f"Port must be between 1 and 65535: {port_int}")
    except ValueError as e:
        raise ValueError(f"Invalid port in endpoint: {port}") from e


def validate_positive_integer(value: str, name: str = "value") -> int:
    """Validate and convert string to positive integer.
    
    Args:
        value: String value to validate
        name: Name of the value for error messages
        
    Returns:
        int: Validated positive integer
        
    Raises:
        ValueError: If validation fails
    """
    if not value:
        raise ValueError(f"{name} must be a non-empty string")
    
    try:
        value_int = int(value.strip())
    except ValueError as e:
        raise ValueError(f"{name} must be a valid integer: {value}") from e
    
    if value_int <= 0:
        raise ValueError(f"{name} must be positive: {value_int}")

    return value_int


_MEMORY_PATTERN = re.compile(r'^\d+[KMGT]$', re.IGNORECASE)
_PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*$")


def validate_memory_string(value: str, name: str = "memory") -> None:
    """Validate a memory/size string like '2G', '512M', '1024K'.

    Args:
        value: Memory string to validate
        name: Field name for error messages

    Raises:
        ValueError: If validation fails
    """
    if not value:
        raise ValueError(f"{name} must be a non-empty string")

    if not _MEMORY_PATTERN.match(value):
        raise ValueError(
            f"Invalid {name} value '{value}' (e.g. 2G, 512M, 1T)"
        )


def validate_package_name(value: str, name: str = "package") -> str:
    """Validate a package name used in apt/system package lookups."""
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{name} must be a non-empty string")

    if not _PACKAGE_NAME_PATTERN.match(normalized_value):
        raise ValueError(f"Invalid {name} name: {value}")

    return normalized_value


def validate_hosted_flags(config: Any) -> None:
    """Validate that required hosted flags are present when --hosted is used.

    Args:
        config: SetupConfig instance

    Raises:
        ValueError: If required flags are missing or invalid
    """
    if not config.hosted_node:
        return

    if not config.container_memory:
        raise ValueError("--memory is required when --hosted is specified")

    if not config.container_storage:
        raise ValueError("--storage is required when --hosted is specified")

    storage_specs: list[list[str]] = []
    if config.container_storage:
        raw_specs = cast(list[object], config.container_storage)
        if raw_specs and isinstance(raw_specs[0], str):
            storage_specs = [cast(list[str], raw_specs)]
        else:
            storage_specs = [cast(list[str], spec) for spec in raw_specs]

    root_seen = False
    seen_types: set[str] = set()

    for spec in storage_specs:
        if len(spec) < 2:
            raise ValueError(
                "--storage requires at least TYPE and POOL"
            )

        storage_type = spec[0]
        if storage_type in seen_types:
            raise ValueError(f"Duplicate --storage TYPE '{storage_type}'")
        seen_types.add(storage_type)

        if storage_type == "root":
            if len(spec) != 3:
                raise ValueError(
                    "--storage root requires TYPE POOL AMOUNT"
                )
            root_seen = True
        elif storage_type == "template":
            if len(spec) != 2:
                raise ValueError(
                    "--storage template requires TYPE POOL"
                )
        else:
            raise ValueError(
                f"--storage TYPE must be one of root, template (got '{storage_type}')"
            )

    if not root_seen:
        raise ValueError("--storage root POOL AMOUNT is required when --hosted is specified")

    validate_memory_string(config.container_memory, "--memory")

    for spec in storage_specs:
        if spec[0] != "root":
            continue
        amount = spec[2]
        validate_memory_string(amount, "--storage AMOUNT")

    if config.container_cores < 1:
        raise ValueError("--cores must be at least 1")
