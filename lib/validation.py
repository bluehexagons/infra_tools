"""Enhanced validation framework extending existing patterns."""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lib.plugin_registry import resolve_validator

if TYPE_CHECKING:
    from lib.config import SetupConfig


def _resolve_plugin_validator(name: str) -> Callable[..., object]:
    """Resolve a plugin-owned validator or parser callable."""

    return resolve_validator(name)


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


def validate_deploy_targets(targets: Optional[list[str]]) -> None:
    """Validate deploy target hostnames before setup or patch execution."""

    if not targets:
        return

    from lib.validators import validate_host

    for target in targets:
        if not target or not target.strip():
            raise ValueError("Deploy target must be a non-empty hostname or IP")
        if not validate_host(target):
            raise ValueError(f"Invalid deploy target host: {target}")


def validate_deploy_specs(deploy_specs: Optional[list[list[str]]]) -> None:
    """Validate deploy specs before setup or patch execution."""

    if not deploy_specs:
        return

    from lib.deploy_utils import parse_deploy_spec
    from lib.validators import validate_host

    for deploy_spec_entry in deploy_specs:
        if len(deploy_spec_entry) != 2:
            raise ValueError("--deploy requires DOMAIN_OR_PATH and GIT_URL")

        deploy_specs_str, git_url = deploy_spec_entry
        if not deploy_specs_str or not str(deploy_specs_str).strip():
            raise ValueError("Deploy target spec must be a non-empty string")
        if not git_url or not str(git_url).strip():
            raise ValueError("Deploy git URL must be a non-empty string")

        for raw_deploy_spec in str(deploy_specs_str).split(","):
            deploy_spec = raw_deploy_spec.strip()
            if not deploy_spec:
                raise ValueError("Deploy target spec list must not contain empty entries")

            if deploy_spec.startswith("/"):
                validate_filesystem_path(deploy_spec, must_exist=False)
                continue

            domain, _path = parse_deploy_spec(deploy_spec)
            if not domain or not validate_host(domain):
                raise ValueError(f"Invalid deploy domain: {domain or deploy_spec}")


def validate_sync_specs(sync_specs: Optional[list[list[str]]]) -> None:
    """Validate sync specs before setup or patch execution."""

    if not sync_specs:
        return

    parse_sync_spec = cast(
        Callable[[list[str]], dict[str, Any]],
        _resolve_plugin_validator("parse_sync_spec"),
    )

    for sync_spec in sync_specs:
        sync_config = parse_sync_spec(sync_spec)
        validate_filesystem_path(sync_config["source"], must_exist=False)
        validate_filesystem_path(sync_config["destination"], must_exist=False)


def validate_scrub_specs(scrub_specs: Optional[list[list[str]]]) -> None:
    """Validate scrub specs before setup or patch execution."""

    if not scrub_specs:
        return

    parse_scrub_spec = cast(
        Callable[[list[str]], dict[str, Any]],
        _resolve_plugin_validator("parse_scrub_spec"),
    )

    for scrub_spec in scrub_specs:
        scrub_config = parse_scrub_spec(scrub_spec)
        validate_filesystem_path(scrub_config["directory"], must_exist=False)
        validate_database_path(scrub_config["database_path"])
        validate_redundancy_percentage(scrub_config["redundancy"])


def validate_smb_mount_specs(smb_mounts: Optional[list[list[str]]]) -> None:
    """Validate SMB mount specs before setup or patch execution."""

    if not smb_mounts:
        return

    from lib.validators import validate_host
    parse_smb_mount_spec = cast(
        Callable[[Optional[list[str]]], dict[str, Any]],
        _resolve_plugin_validator("parse_smb_mount_spec"),
    )

    for mount_spec in smb_mounts:
        mount_config = parse_smb_mount_spec(mount_spec)
        validate_filesystem_path(mount_config["mountpoint"], must_exist=False)
        if not validate_host(mount_config["ip"]):
            raise ValueError(f"Invalid SMB mount host: {mount_config['ip']}")
        if not mount_config["share"] or "/" in mount_config["share"] or "\\" in mount_config["share"] or " " in mount_config["share"]:
            raise ValueError(f"Invalid share name (cannot contain /, \\, or spaces): {mount_config['share']}")
        if mount_config["subdir"] and not mount_config["subdir"].startswith("/"):
            raise ValueError(f"Subdirectory must start with /: {mount_config['subdir']}")


def validate_samba_share_specs(
    samba_shares: Optional[list[list[str]]],
    share_credentials: Optional[list[list[str]]] = None,
) -> None:
    """Validate Samba share specs before setup or patch execution."""

    if not samba_shares:
        return

    parse_share_credentials = cast(
        Callable[[Optional[list[list[str]]]], dict[str, str]],
        _resolve_plugin_validator("parse_share_credentials"),
    )
    parse_share_spec = cast(
        Callable[[Optional[list[str]], Optional[dict[str, str]]], dict[str, Any]],
        _resolve_plugin_validator("parse_share_spec"),
    )

    credentials = parse_share_credentials(share_credentials)

    for share_spec in samba_shares:
        share_config = parse_share_spec(share_spec, credentials)
        share_name = share_config["share_name"]
        if not share_name or "/" in share_name or "\\" in share_name or " " in share_name:
            raise ValueError(f"Invalid Samba share name (cannot contain /, \\, or spaces): {share_name}")

        if not share_config["paths"]:
            raise ValueError(f"No paths specified for share: {share_name}")

        for path in cast(list[str], share_config["paths"]):
            if not os.path.isabs(path):
                raise ValueError(f"Share path must be absolute: {path}")
            validate_filesystem_path(path, must_exist=False)

        if not share_config["users"]:
            raise ValueError(f"No users specified for share: {share_name}")


def validate_samba_share_credentials(config: "SetupConfig") -> None:
    """Validate Samba share credentials through the plugin registry."""

    validator = cast(
        Callable[["SetupConfig"], None],
        _resolve_plugin_validator("validate_samba_share_credentials"),
    )
    validator(config)


def validate_ssl_email(email: Optional[str]) -> None:
    """Validate the optional SSL registration email before setup or patch execution."""

    if not email:
        return

    from lib.notifications import NotificationConfig, validate_notification_config

    try:
        validate_notification_config(NotificationConfig(type="mailbox", target=email))
    except ValueError as exc:
        raise ValueError(f"Invalid SSL email address: {email}") from exc


def validate_apt_packages(packages: Optional[list[str]]) -> None:
    """Validate custom apt package names before setup or patch execution."""

    if not packages:
        return

    for package in packages:
        validate_package_name(package, name="--apt-install")


def validate_timezone_name(timezone: Optional[str]) -> None:
    """Validate a timezone identifier before setup or patch execution."""

    if not timezone:
        return

    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone}") from exc


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
_NETWORK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NETWORK_PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")


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


def validate_network_name(value: str, name: str = "network name") -> str:
    """Validate a generic network inventory name or role label."""

    normalized_value = value.strip()
    if not normalized_value or not _NETWORK_NAME_PATTERN.match(normalized_value):
        raise ValueError(
            f"{name} must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, or hyphens"
        )
    return normalized_value


def validate_network_provider(value: str) -> str:
    """Validate a network inventory provider tag."""

    normalized_value = value.strip()
    if not normalized_value or not _NETWORK_PROVIDER_PATTERN.match(normalized_value):
        raise ValueError(f"Invalid provider name: {value}")
    return normalized_value


def validate_network_ip(value: str, name: str = "network address") -> str:
    """Validate an IP address and return its normalized text form."""

    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {value}") from exc


def validate_network_cidr(value: str, name: str = "network CIDR") -> str:
    """Validate a CIDR and return its normalized text form."""

    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {value}") from exc


def validate_network_ip_or_cidr(value: str, name: str = "network address") -> str:
    """Validate either an IP address or a CIDR range."""

    if "/" in value:
        return validate_network_cidr(value, name)
    return validate_network_ip(value, name)


def validate_network_vlan_id(value: int | str) -> int:
    """Validate an IEEE 802.1Q VLAN ID."""

    try:
        vlan_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid VLAN ID: {value}") from exc
    if not 1 <= vlan_id <= 4094:
        raise ValueError(f"VLAN ID must be between 1 and 4094: {vlan_id}")
    return vlan_id


def validate_hosted_flags(config: Any) -> None:
    """Validate that required hosted flags are present when --hosted is used.

    Args:
        config: SetupConfig instance

    Raises:
        ValueError: If required flags are missing or invalid
    """
    if not config.hosted_node:
        return

    from lib.validators import validate_host

    if not validate_host(config.hosted_node):
        raise ValueError(f"Invalid hosted node host: {config.hosted_node}")

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

    machine_type = getattr(config, "machine_type", None)
    vm_image = getattr(config, "vm_image", None)
    if machine_type == "vm":
        from lib.cloud_images import parse_image_argument, resolve_cloud_image
        for spec in storage_specs:
            if spec[0] == "template":
                raise ValueError(
                    "--storage template is not used for VMs; use --image instead"
                )
        if vm_image:
            parse_image_argument(vm_image)
        else:
            base = getattr(config, "container_base", None) or "debian"
            resolve_cloud_image(base)
    elif vm_image:
        raise ValueError("--image requires --machine vm")
