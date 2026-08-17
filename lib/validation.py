"""Enhanced validation framework extending existing patterns."""

from __future__ import annotations

import ipaddress
import os
import pwd
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lib.plugin_registry import resolve_validator

if TYPE_CHECKING:
    from lib.config import SetupConfig


def _resolve_plugin_validator(name: str) -> Callable[..., object]:
    """Resolve a plugin-owned validator or parser callable."""

    return resolve_validator(name)


def _validate_no_control_characters(value: str, name: str) -> None:
    """Reject values that could add lines to generated configuration files."""

    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} must not contain control characters")


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

    _validate_no_control_characters(path, "Path")
    
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


_CHANNEL_VERSION_PATTERN = re.compile(
    r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:[-+][0-9A-Za-z.-]+)?$"
)
_CHANNEL_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9._/-]*[A-Za-z0-9_])?$")
_CHANNEL_COMMIT_PATTERN = re.compile(r"^[0-9A-Fa-f]{4,64}$")


def validate_channel(channel: str) -> str:
    """Validate and return an infra_tools release channel selector."""

    if not isinstance(channel, str) or not channel:
        raise ValueError("Channel must be a non-empty string")
    _validate_no_control_characters(channel, "Channel")

    if channel in {"stable", "dev"}:
        return channel

    if channel.startswith("v"):
        if not _CHANNEL_VERSION_PATTERN.fullmatch(channel):
            raise ValueError(
                "Version channels must use a semantic version such as v1.2.3"
            )
        return channel

    if channel.startswith("branch-"):
        branch = channel.removeprefix("branch-")
        if (
            not _CHANNEL_BRANCH_PATTERN.fullmatch(branch)
            or branch.startswith(".")
            or branch.endswith(".")
            or ".." in branch
            or "//" in branch
            or "@{" in branch
        ):
            raise ValueError(f"Invalid branch channel: {channel}")
        return channel

    if channel.startswith("commit-"):
        commit = channel.removeprefix("commit-")
        if not _CHANNEL_COMMIT_PATTERN.fullmatch(commit):
            raise ValueError(
                "Commit channels must contain a hexadecimal commit hash"
            )
        return channel

    raise ValueError(
        "Unknown channel; use stable, dev, v<version>, branch-<branch>, "
        "or commit-<hash>"
    )


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


def validate_gogs_settings(gogs: Optional[list[str]]) -> None:
    """Validate Gogs setup arguments before setup or patch execution."""
    if not gogs:
        return

    if len(gogs) not in (1, 2):
        raise ValueError("--gogs requires DOMAIN[:PORT] and optional DATA_PATH")

    spec = str(gogs[0]).strip()
    if not spec:
        raise ValueError("Gogs target spec must be a non-empty string")

    from web.gogs_steps import parse_gogs_spec
    from lib.validators import validate_host

    domain, _port = parse_gogs_spec(spec, strict=True)
    if domain and not validate_host(domain):
        raise ValueError(f"Invalid Gogs domain: {domain}")

    if len(gogs) == 2:
        data_path = str(gogs[1]).strip()
        if not os.path.isabs(data_path):
            raise ValueError(f"Gogs data path must be absolute: {data_path}")
        validate_filesystem_path(data_path, must_exist=False)


def validate_antistatic_settings(config: "SetupConfig") -> None:
    """Validate antistatic-server deployment and optional admin settings."""
    if not config.antistatic_server:
        if config.antistatic_admin is not None:
            raise ValueError("--antistatic-admin requires --antistatic-server")
        return

    from game.antistatic_steps import parse_antistatic_spec
    from lib.validators import validate_host

    domain, _port = parse_antistatic_spec(config.antistatic_server, strict=True)
    if domain and not validate_host(domain):
        raise ValueError(f"Invalid Antistatic server domain: {domain}")

    if not config.antistatic_admin:
        return
    if not domain:
        raise ValueError("--antistatic-admin requires a hostname-based reverse proxy deployment")
    if not (config.enable_ssl or config.enable_cloudflare):
        raise ValueError("--antistatic-admin requires --ssl or --cloudflare")

    username = config.antistatic_admin
    if username != username.strip() or ":" in username or "," in username:
        raise ValueError(f"Invalid Antistatic admin username: {username}")
    if any(ord(char) < 32 or ord(char) == 127 for char in username):
        raise ValueError("Antistatic admin username must not contain control characters")

    password = None
    for credential in config.share_credentials or []:
        if len(credential) == 2 and credential[0] == username:
            password = credential[1]
            break
    if password is None:
        raise ValueError(f"Missing credential for Antistatic admin: {username}")
    if any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise ValueError("Antistatic admin password must not contain control characters")


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

    mountpoints: set[str] = set()
    for mount_spec in smb_mounts:
        mount_config = parse_smb_mount_spec(mount_spec)
        mountpoint = mount_config["mountpoint"]
        validate_filesystem_path(mountpoint, must_exist=False)
        normalized_mountpoint = os.path.normpath(mountpoint)
        if normalized_mountpoint != mountpoint or not normalized_mountpoint.startswith("/mnt/"):
            raise ValueError(
                "SMB mountpoint must be a normalized directory below /mnt: "
                f"{mountpoint}"
            )
        if normalized_mountpoint in mountpoints:
            raise ValueError(f"Duplicate SMB mountpoint: {mountpoint}")
        mountpoints.add(normalized_mountpoint)
        if not validate_host(mount_config["ip"]):
            raise ValueError(f"Invalid SMB mount host: {mount_config['ip']}")
        if not mount_config["username"] or not mount_config["password"]:
            raise ValueError("SMB mount credentials must include a non-empty username and password")
        _validate_no_control_characters(mount_config["username"], "SMB mount username")
        _validate_no_control_characters(mount_config["password"], "SMB mount password")
        if (
            not mount_config["share"]
            or "/" in mount_config["share"]
            or "\\" in mount_config["share"]
            or any(char.isspace() for char in mount_config["share"])
        ):
            raise ValueError(f"Invalid share name (cannot contain /, \\, or spaces): {mount_config['share']}")
        _validate_no_control_characters(mount_config["subdir"], "SMB mount subdirectory")
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

    share_names: set[str] = set()
    for share_spec in samba_shares:
        share_config = parse_share_spec(share_spec, credentials)
        share_name = share_config["share_name"]
        validate_samba_share_name(share_name)
        if share_name in share_names:
            raise ValueError(f"Duplicate Samba share name: {share_name}")
        share_names.add(share_name)

        if not share_config["paths"]:
            raise ValueError(f"No paths specified for share: {share_name}")

        if len(share_config["paths"]) != 1:
            raise ValueError("Samba shares support exactly one path; create one --share per directory")

        for path in cast(list[str], share_config["paths"]):
            if not os.path.isabs(path):
                raise ValueError(f"Share path must be absolute: {path}")
            if os.path.normpath(path) == "/":
                raise ValueError("Samba share path must not be the filesystem root")
            validate_filesystem_path(path, must_exist=False)

        if not share_config["users"]:
            raise ValueError(f"No users specified for share: {share_name}")

        from lib.validators import validate_username

        for user in cast(list[dict[str, str]], share_config["users"]):
            username = user["username"]
            password = user["password"]
            if not validate_username(username):
                raise ValueError(f"Invalid Samba username: {username}")
            if not password:
                raise ValueError(f"Samba password must not be empty for user: {username}")
            _validate_no_control_characters(username, "Samba username")
            _validate_no_control_characters(password, "Samba password")


def validate_samba_share_name(share_name: str) -> None:
    """Validate a Samba share name used in config sections and Unix groups."""

    _validate_no_control_characters(share_name, "Samba share name")
    if not share_name or "/" in share_name or "\\" in share_name or " " in share_name:
        raise ValueError(
            f"Invalid Samba share name (cannot contain /, \\, or spaces): {share_name}"
        )
    if not re.fullmatch(r"[A-Za-z0-9._-]+", share_name):
        raise ValueError(
            "Invalid Samba share name (use only letters, numbers, dots, "
            f"underscores, and hyphens): {share_name}"
        )
    if len(f"smb_{share_name}_write") > 32:
        raise ValueError(f"Samba share name is too long for its Unix group: {share_name}")


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
_MEMORY_UNIT_TO_KIB = {
    "K": 1,
    "M": 1024,
    "G": 1024 * 1024,
    "T": 1024 * 1024 * 1024,
}
_PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*$")
_ENVIRONMENT_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NETWORK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NETWORK_PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
_NETWORK_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}$")
_HOSTNAME_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_GIT_SCP_URL_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[^:\s]+:.+$")
_SAFE_REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def _memory_string_kib(value: str, name: str) -> int:
    """Validate a size string and return its value in KiB."""
    validate_memory_string(value, name)
    amount = int(value[:-1])
    if amount <= 0:
        raise ValueError(f"{name} must be positive")
    return amount * _MEMORY_UNIT_TO_KIB[value[-1].upper()]


def validate_package_name(value: str, name: str = "package") -> str:
    """Validate a package name used in apt/system package lookups."""
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{name} must be a non-empty string")

    if not _PACKAGE_NAME_PATTERN.match(normalized_value):
        raise ValueError(f"Invalid {name} name: {value}")

    return normalized_value


_DEBIAN_CODENAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def validate_debian_codename(value: str) -> str:
    """Validate a Debian release codename used in APT source suites."""

    if not isinstance(value, str) or not _DEBIAN_CODENAME_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid Debian release codename: {value}")
    return value


def validate_environment_variable_name(
    value: str,
    name: str = "environment variable",
) -> str:
    """Validate a shell environment variable name without normalizing it."""

    if not isinstance(value, str) or not _ENVIRONMENT_VARIABLE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid {name} name {value!r}; expected a letter or underscore "
            "followed by letters, digits, or underscores"
        )
    return value


def _repo_name_from_git_url(git_url: str) -> str:
    repo_name = git_url.rstrip('/').split('/')[-1]
    if ':' in repo_name:
        repo_name = repo_name.rsplit(':', 1)[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return repo_name


def validate_agent_repositories(repositories: Optional[list[str]]) -> None:
    """Validate git URLs supplied through --repo for agent VM workspaces."""
    if not repositories:
        return

    seen_repo_names: set[str] = set()
    for repository in repositories:
        if not isinstance(repository, str):
            raise ValueError("--repo requires a git URL")

        git_url = repository.strip()
        if not git_url:
            raise ValueError("--repo requires a non-empty git URL")
        if git_url != repository:
            raise ValueError(f"Invalid --repo git URL: {repository}")
        if git_url.startswith('-'):
            raise ValueError(f"Invalid --repo git URL: {repository}")
        if any(ord(char) < 32 or ord(char) == 127 for char in git_url):
            raise ValueError(f"Invalid --repo git URL: {repository}")

        parsed = urlparse(git_url)
        if parsed.scheme:
            if parsed.scheme not in {"git", "http", "https", "ssh"} or not parsed.netloc:
                raise ValueError(f"Invalid --repo git URL: {repository}")
            if parsed.password is not None or (
                parsed.scheme in {"http", "https"} and parsed.username is not None
            ):
                raise ValueError(
                    "--repo URLs must not contain embedded credentials"
                )
        elif not _GIT_SCP_URL_PATTERN.match(git_url):
            raise ValueError(
                "--repo must be an https://, ssh://, git://, or git@host:path git URL"
            )

        repo_name = _repo_name_from_git_url(git_url)
        if not repo_name or not _SAFE_REPO_NAME_PATTERN.match(repo_name):
            raise ValueError(f"Invalid --repo repository name derived from URL: {repository}")
        if repo_name in seen_repo_names:
            raise ValueError(f"Duplicate --repo repository name: {repo_name}")
        seen_repo_names.add(repo_name)


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


def validate_system_hostname(value: str) -> str:
    """Validate a static system hostname or fully qualified domain name."""

    normalized = value.strip()
    if not normalized or normalized != value or len(normalized) > 63:
        raise ValueError(f"Invalid system hostname: {value}")
    _validate_no_control_characters(normalized, "System hostname")
    if normalized.endswith("."):
        raise ValueError("System hostname must not end with a dot")
    if any(not _HOSTNAME_LABEL_PATTERN.fullmatch(label) for label in normalized.split(".")):
        raise ValueError(f"Invalid system hostname: {value}")
    return normalized


def validate_network_interface_name(value: str) -> str:
    """Validate a Linux network interface name used in generated config."""

    normalized = value.strip()
    if normalized != value or not _NETWORK_INTERFACE_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid network interface: {value}")
    return normalized


def _validate_static_interface(value: str, version: int, flag: str) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface:
    if "/" not in value:
        raise ValueError(f"{flag} requires CIDR notation with a prefix length")
    try:
        interface = ipaddress.ip_interface(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {flag} address: {value}") from exc
    if interface.version != version:
        family = "IPv4" if version == 4 else "IPv6"
        raise ValueError(f"{flag} requires an {family} address")
    if interface.ip.is_unspecified or interface.ip.is_multicast:
        raise ValueError(f"Invalid {flag} address: {value}")
    if (
        version == 4
        and interface.network.prefixlen < 31
        and interface.ip in {interface.network.network_address, interface.network.broadcast_address}
    ):
        raise ValueError(f"{flag} must be a usable host address: {value}")
    return interface


def validate_network_setup_settings(config: Any) -> None:
    """Validate hostname and persistent static network setup options."""

    hostname = getattr(config, "system_hostname", None)
    ipv4_value = getattr(config, "static_ipv4", None)
    ipv6_value = getattr(config, "static_ipv6", None)
    gateway4_value = getattr(config, "network_gateway4", None)
    gateway6_value = getattr(config, "network_gateway6", None)
    dns_values = getattr(config, "network_dns", None) or []
    interface_name = getattr(config, "network_interface", None)
    activate_network = bool(getattr(config, "activate_network", False))

    if hostname:
        validate_system_hostname(hostname)

    network_requested = any(
        (ipv4_value, ipv6_value, gateway4_value, gateway6_value, dns_values, interface_name)
    )
    if getattr(config, "system_type", None) == "server_proxmox" and (hostname or network_requested):
        raise ValueError(
            "--hostname and static network options are not supported for server_proxmox; "
            "changing Proxmox node identity or bridge networking requires a node-specific plan"
        )

    ipv4_interface = _validate_static_interface(ipv4_value, 4, "--ip") if ipv4_value else None
    ipv6_interface = _validate_static_interface(ipv6_value, 6, "--ipv6") if ipv6_value else None

    if activate_network and not (ipv4_interface or ipv6_interface):
        raise ValueError("--activate-network requires --ip or --ipv6")

    if activate_network:
        setup_host = str(getattr(config, "host", "")).lower().rstrip(".")
        local_host = setup_host == "localhost"
        try:
            local_host = local_host or ipaddress.ip_address(setup_host).is_loopback
        except ValueError:
            pass
        if local_host:
            raise ValueError(
                "--activate-network must run from a separate controller so the new "
                "address can be verified externally"
            )

    if gateway4_value:
        if not ipv4_interface:
            raise ValueError("--gateway requires --ip")
        try:
            gateway4 = ipaddress.ip_address(gateway4_value)
        except ValueError as exc:
            raise ValueError(f"Invalid IPv4 gateway: {gateway4_value}") from exc
        if gateway4.version != 4 or gateway4.is_unspecified or gateway4.is_multicast:
            raise ValueError(f"Invalid IPv4 gateway: {gateway4_value}")
        if gateway4 == ipv4_interface.ip or gateway4 not in ipv4_interface.network:
            raise ValueError(
                f"IPv4 gateway must be another address in {ipv4_interface.network}"
            )
        if (
            ipv4_interface.network.prefixlen < 31
            and gateway4
            in {
                ipv4_interface.network.network_address,
                ipv4_interface.network.broadcast_address,
            }
        ):
            raise ValueError(f"IPv4 gateway must be a usable host address: {gateway4_value}")

    if gateway6_value:
        if not ipv6_interface:
            raise ValueError("--gateway6 requires --ipv6")
        try:
            gateway6 = ipaddress.ip_address(gateway6_value)
        except ValueError as exc:
            raise ValueError(f"Invalid IPv6 gateway: {gateway6_value}") from exc
        if gateway6.version != 6 or gateway6.is_unspecified or gateway6.is_multicast:
            raise ValueError(f"Invalid IPv6 gateway: {gateway6_value}")
        if gateway6 == ipv6_interface.ip or (
            not gateway6.is_link_local and gateway6 not in ipv6_interface.network
        ):
            raise ValueError(
                "IPv6 gateway must be link-local or another address in "
                f"{ipv6_interface.network}"
            )

    if not ipv4_interface and not ipv6_interface and (dns_values or interface_name):
        raise ValueError("A network DNS or interface option requires --ip or --ipv6")

    normalized_dns: set[str] = set()
    for dns_value in dns_values:
        try:
            dns_address = ipaddress.ip_address(dns_value)
        except ValueError as exc:
            raise ValueError(f"Invalid DNS server address: {dns_value}") from exc
        if dns_address.is_unspecified or dns_address.is_multicast:
            raise ValueError(f"Invalid DNS server address: {dns_value}")
        normalized = str(dns_address)
        if normalized in normalized_dns:
            raise ValueError(f"Duplicate DNS server address: {normalized}")
        normalized_dns.add(normalized)

    if interface_name:
        validate_network_interface_name(interface_name)

    if getattr(config, "hosted_node", None) and (ipv4_interface or ipv6_interface):
        try:
            setup_host = ipaddress.ip_address(str(getattr(config, "host", "")))
        except ValueError:
            if not ipv4_interface:
                raise ValueError(
                    "Proxmox provisioning requires a literal IPv4 setup target"
                )
            return
        if setup_host.version == 6 and not ipv4_interface:
            raise ValueError(
                "Proxmox provisioning currently requires an IPv4 target for the SSH handoff"
            )
        configured = ipv4_interface if setup_host.version == 4 else ipv6_interface
        if configured is None or configured.ip != setup_host:
            if activate_network:
                return
            raise ValueError(
                "For Proxmox provisioning, the literal setup host must match the address "
                "provided by --ip or --ipv6 unless --activate-network is used for an "
                "existing guest"
            )


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
    """Validate Proxmox guest options used with ``--provision-on``.

    Args:
        config: SetupConfig instance

    Raises:
        ValueError: If required flags are missing or invalid
    """
    balloon_min = getattr(config, "vm_balloon_min", None)
    if not config.hosted_node:
        if balloon_min:
            raise ValueError("--balloon-min requires --provision-on")
        return

    from lib.validators import validate_host

    if not validate_host(config.hosted_node):
        raise ValueError(f"Invalid Proxmox node host: {config.hosted_node}")

    if not config.container_memory:
        raise ValueError("--memory is required with --provision-on")

    if not config.container_storage:
        raise ValueError("--storage is required with --provision-on")

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
        raise ValueError("--storage root [POOL] AMOUNT is required with --provision-on")

    memory_kib = _memory_string_kib(config.container_memory, "--memory")

    for spec in storage_specs:
        if spec[0] != "root":
            continue
        amount = spec[2]
        validate_memory_string(amount, "--storage AMOUNT")

    if config.container_cores < 1:
        raise ValueError("--cores must be at least 1")

    hosted_bridge = getattr(config, "hosted_bridge", None)
    if hosted_bridge:
        validate_network_interface_name(hosted_bridge)

    machine_type = getattr(config, "machine_type", None)
    vm_image = getattr(config, "vm_image", None)
    if machine_type == "vm":
        if balloon_min:
            balloon_kib = _memory_string_kib(balloon_min, "--balloon-min")
            if balloon_kib > memory_kib:
                raise ValueError("--balloon-min cannot exceed --memory")
        ssh_key = getattr(config, "ssh_key", None)
        if not ssh_key:
            raise ValueError(
                "VM provisioning requires --key PATH with a matching PATH.pub"
            )
        pubkey_path = f"{ssh_key}.pub"
        if not os.path.isfile(pubkey_path) or os.path.getsize(pubkey_path) <= 0:
            raise ValueError(
                f"VM provisioning requires a readable SSH public key: {pubkey_path}"
            )

        if not getattr(config, "static_ipv4", None):
            try:
                target_ip = ipaddress.ip_address(str(getattr(config, "host", "")))
            except ValueError as exc:
                raise ValueError(
                    "VM provisioning requires a literal IPv4 target"
                ) from exc
            if target_ip.version != 4:
                raise ValueError(
                    "VM provisioning currently requires an IPv4 target for the SSH handoff"
                )

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
    else:
        if balloon_min:
            raise ValueError("--balloon-min requires --machine vm")
        if vm_image:
            raise ValueError("--image requires --machine vm")


def validate_rdp_settings(config: Any) -> None:
    """Validate credentials and network policy required for xRDP.

    xRDP authenticates against the Unix account password. Hosted cloud images
    are deliberately provisioned key-only, so remote or newly-created desktop
    accounts must receive a password. A local setup may explicitly reuse the
    password of an already-existing account.
    """
    use_existing_password = bool(getattr(config, "rdp_existing_password", False))
    if not getattr(config, "enable_rdp", False):
        if use_existing_password:
            raise ValueError("--rdp-existing-password requires --rdp")
        has_rdp_policy = bool(getattr(config, "rdp_allowed_sources", None)) or any(
            (
                getattr(config, "rdp_bind_address", "0.0.0.0") != "0.0.0.0",
                not bool(getattr(config, "rdp_clipboard", True)),
                bool(getattr(config, "rdp_drive_redirection", False)),
                bool(getattr(config, "rdp_audio", False)),
                getattr(config, "rdp_max_sessions", 10) != 10,
                bool(getattr(config, "rdp_kill_disconnected", False)),
                getattr(config, "rdp_disconnected_timeout", 0) != 0,
                getattr(config, "rdp_idle_timeout", 0) != 0,
            )
        )
        if has_rdp_policy:
            raise ValueError("RDP policy options require --rdp")
        return

    username = str(getattr(config, "username", "")).strip()
    if username == "root":
        raise ValueError("--rdp cannot be used with the root account")

    password = getattr(config, "password", None)
    if use_existing_password:
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if str(getattr(config, "host", "")).strip().lower() not in local_hosts:
            raise ValueError("--rdp-existing-password requires a local setup target")
        if password is not None:
            raise ValueError("--rdp-existing-password cannot be combined with --password")
        try:
            pwd.getpwnam(username)
        except KeyError as exc:
            raise ValueError(
                "--rdp-existing-password requires an existing local desktop account"
            ) from exc

        try:
            password_status = subprocess.run(
                ["passwd", "-S", username],
                capture_output=True,
                text=True,
                env={**os.environ, "LC_ALL": "C"},
            )
        except OSError as exc:
            raise ValueError(
                "--rdp-existing-password could not inspect the account password status"
            ) from exc
        status_fields = (password_status.stdout or "").split()
        if password_status.returncode != 0 or len(status_fields) < 2:
            raise ValueError(
                "--rdp-existing-password could not inspect the account password status"
            )
        if status_fields[1] != "P":
            raise ValueError(
                "--rdp-existing-password requires an existing account with an unlocked password"
            )
    else:
        if not isinstance(password, str) or not password.strip():
            raise ValueError("--rdp requires --password for the desktop login account")
        _validate_no_control_characters(password, "RDP password")

    bind_address = getattr(config, "rdp_bind_address", "0.0.0.0")
    if not isinstance(bind_address, str):
        raise ValueError("--rdp-bind-address requires an IP address")
    validate_network_ip(bind_address, "RDP bind address")

    normalized_sources: set[str] = set()
    for source in getattr(config, "rdp_allowed_sources", None) or []:
        if not isinstance(source, str):
            raise ValueError("--rdp-source requires an IP address or CIDR")
        normalized = validate_network_ip_or_cidr(source, "RDP source")
        if normalized in normalized_sources:
            raise ValueError(f"Duplicate RDP source: {normalized}")
        normalized_sources.add(normalized)

    max_sessions = getattr(config, "rdp_max_sessions", 10)
    if not isinstance(max_sessions, int) or isinstance(max_sessions, bool):
        raise ValueError("--rdp-max-sessions requires an integer")
    if not 1 <= max_sessions <= 100:
        raise ValueError("--rdp-max-sessions must be between 1 and 100")

    disconnected_timeout = getattr(config, "rdp_disconnected_timeout", 0)
    idle_timeout = getattr(config, "rdp_idle_timeout", 0)
    for name, value in (
        ("--rdp-disconnected-timeout", disconnected_timeout),
        ("--rdp-idle-timeout", idle_timeout),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    kill_disconnected = bool(getattr(config, "rdp_kill_disconnected", False))
    if kill_disconnected and disconnected_timeout == 0:
        raise ValueError(
            "--rdp-kill-disconnected requires a positive --rdp-disconnected-timeout"
        )
    if not kill_disconnected and disconnected_timeout != 0:
        raise ValueError(
            "--rdp-disconnected-timeout requires --rdp-kill-disconnected"
        )
