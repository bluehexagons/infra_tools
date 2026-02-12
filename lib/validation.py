"""Enhanced validation framework extending existing patterns."""

from __future__ import annotations
import os
import re
from pathlib import Path


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