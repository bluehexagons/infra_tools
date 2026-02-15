"""Systemd service creation for deployed applications."""

from __future__ import annotations
import os
import secrets
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.remote_utils import run


def _unit_has_install_section(unit_file: str) -> bool:
    """Return True when a unit file contains an [Install] section."""
    try:
        with open(unit_file, "r", encoding="utf-8") as f:
            return "[Install]" in f.read()
    except OSError:
        return False


def cleanup_systemd_unit(unit_name: str, unit_type: str = "service") -> None:
    """Stop, disable, and remove a single systemd unit file if it exists.
    
    This is a low-level helper for cleaning up individual unit files.
    For most use cases, use cleanup_service() instead which automatically
    handles associated timers.
    
    Args:
        unit_name: Base name of the unit (without extension)
        unit_type: Type of unit - "service", "timer", or "mount"
    """
    unit_file = f"/etc/systemd/system/{unit_name}.{unit_type}"
    
    # Stop and disable the unit
    if os.path.exists(unit_file):
        run(f"systemctl stop {shlex.quote(unit_name)}.{unit_type}", check=False)
        run(f"systemctl disable {shlex.quote(unit_name)}.{unit_type}", check=False)
        os.remove(unit_file)
        run("systemctl daemon-reload", check=False)


def cleanup_service(service_name: str) -> None:
    """Stop, disable, and remove a service and its timer if they exist.
    
    This is the primary cleanup function for systemd services. It automatically
    checks for and cleans up any associated timer before cleaning up the service.
    Use this for all service cleanup operations.
    
    Args:
        service_name: Base name of the service (without .service/.timer extension)
                      If the service has a timer (service_name.timer), it will be
                      automatically detected and cleaned up as well.
    
    Examples:
        # Cleans up both myapp.service and myapp.timer (if timer exists)
        cleanup_service("myapp")
        
        # Cleans up just the timer
        cleanup_service("myapp-update")
    """
    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    
    needs_reload = False
    
    # Stop and disable timer first (timers trigger services, so stop timer before service)
    if os.path.exists(timer_file):
        run(f"systemctl stop {shlex.quote(service_name)}.timer", check=False)
        run(f"systemctl disable {shlex.quote(service_name)}.timer", check=False)
        os.remove(timer_file)
        needs_reload = True
    
    # Stop service; disable only when it declares an [Install] section
    if os.path.exists(service_file):
        run(f"systemctl stop {shlex.quote(service_name)}.service", check=False)
        if _unit_has_install_section(service_file):
            run(f"systemctl disable {shlex.quote(service_name)}.service", check=False)
        os.remove(service_file)
        needs_reload = True
    
    # Reload systemd to reflect changes
    if needs_reload:
        run("systemctl daemon-reload", check=False)


# Keep backward compatibility with old function name
cleanup_existing_systemd_unit = cleanup_systemd_unit
cleanup_service_and_timer = cleanup_service


def cleanup_all_infra_services(dry_run: bool = False) -> None:
    """Remove all systemd units created by infra_tools to ensure clean deployment state.
    
    This function treats the current deployment command as the desired baseline state.
    It removes ALL previously deployed services, timers, and mounts that match
    infra_tools naming patterns, ensuring no orphaned units remain from previous
    deployments with different configurations.
    
    Args:
        dry_run: If True, only print what would be removed without actually removing
    
    Examples:
        # Clean up all infra_tools services before applying new configuration
        cleanup_all_infra_services()
        
        # Preview what would be removed (dry run)
        cleanup_all_infra_services(dry_run=True)
    """
    systemd_dir = "/etc/systemd/system"
    # Patterns for infra_tools-created units
    # These patterns match services, timers, and mounts created by various components
    infra_patterns = [
        # Sync services and timers
        r"^sync-.*\.service$",
        r"^sync-.*\.timer$",
        # Scrub services and timers
        r"^scrub-.*\.service$",
        r"^scrub-.*\.timer$",
        r"^scrub-.*-update\.service$",
        r"^scrub-.*-update\.timer$",
        # Backup services
        r"^backup-.*\.service$",
        r"^backup-.*\.timer$",
        # Node.js app services
        r"^node-.*\.service$",
        # Rails app services
        r"^rails-.*\.service$",
        # Auto-update timers
        r"^auto-update-ruby\.service$",
        r"^auto-update-ruby\.timer$",
        r"^auto-update-node\.service$",
        r"^auto-update-node\.timer$",
        # Auto-restart service
        r"^auto-restart-if-needed\.service$",
        r"^auto-restart-if-needed\.timer$",
        # SMB mount units
        r"^mnt-.*\.mount$",
    ]
    
    units_to_remove = []
    
    # Scan for matching unit files
    if os.path.exists(systemd_dir):
        for filename in os.listdir(systemd_dir):
            for pattern in infra_patterns:
                if re.match(pattern, filename):
                    units_to_remove.append(filename)
                    break
    
    if not units_to_remove:
        if not dry_run:
            print("  No existing infra_tools services found")
        return
    
    if dry_run:
        print(f"  [DRY RUN] Would remove {len(units_to_remove)} unit(s):")
        for unit in sorted(units_to_remove):
            print(f"    - {unit}")
        return
    
    print(f"  Cleaning up {len(units_to_remove)} existing infra_tools unit(s)...")
    
    # Group by unit type for proper stopping order
    timers = [u for u in units_to_remove if u.endswith(".timer")]
    services = [u for u in units_to_remove if u.endswith(".service")]
    mounts = [u for u in units_to_remove if u.endswith(".mount")]
    others = [u for u in units_to_remove if not any(u.endswith(ext) for ext in [".timer", ".service", ".mount"])]
    
    # Stop in order: timers first (they trigger services), then services, then mounts, then others
    for unit in timers + services + mounts + others:
        unit_type = unit.rsplit(".", 1)[1]
        unit_path = os.path.join(systemd_dir, unit)
        
        # Stop the unit (ignore errors if not running)
        run(f"systemctl stop {shlex.quote(unit)}", check=False)
        
        # Disable timers/mounts and services with an [Install] section.
        if unit_type in ("timer", "mount") or (
            unit_type == "service" and _unit_has_install_section(unit_path)
        ):
            run(f"systemctl disable {shlex.quote(unit)}", check=False)
        
        # Remove the file
        try:
            os.remove(unit_path)
            print(f"    ✓ Removed {unit}")
        except OSError as e:
            print(f"    ✗ Failed to remove {unit}: {e}")
    
    # Reload systemd to reflect all changes
    run("systemctl daemon-reload", check=False)
    run("systemctl reset-failed", check=False)
    
    print(f"  ✓ Cleaned up {len(units_to_remove)} unit(s)")


def generate_node_service(app_name: str, app_path: str, port: int = 4000,
                         web_user: str = "www-data", web_group: str = "www-data",
                         build_dir: str = "dist") -> str:
    """Generate systemd service configuration for a Node.js application."""
    return f"""[Unit]
Description=Node app: {app_name}
After=network.target

[Service]
Type=simple
User={web_user}
Group={web_group}
WorkingDirectory={app_path}
Environment="NODE_ENV=production"
Environment="PORT={port}"
ExecStart=/usr/local/bin/npx -y serve -s {build_dir} -l {port}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def create_node_service(app_name: str, app_path: str, port: int,
                       web_user: str, web_group: str) -> None:
    """Create and enable a Node.js systemd service."""
    service_name = f"node-{app_name}"
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    # Clean up existing service before creating new one
    cleanup_service(service_name)
    
    build_dir = "dist"
    if os.path.exists(os.path.join(app_path, "build")):
        build_dir = "build"
    elif os.path.exists(os.path.join(app_path, "out")):
        build_dir = "out"
    
    service_content = generate_node_service(app_name, app_path, port, web_user, web_group, build_dir)
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write service file {service_file}. Need root permissions.") from e
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}")
    run(f"systemctl restart {service_name}")
    
    print(f"  ✓ Created and started systemd service: {service_name}")
    
    import time
    time.sleep(1)
    
    result = run(f"systemctl is-active {service_name}", check=False)
    if result.returncode != 0:
        print(f"  ⚠ Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
    else:
        print(f"  ✓ {service_name} is running")


def generate_rails_service(app_name: str, app_path: str, secret_key_base: str, port: int = 3000,
                          web_user: str = "www-data", web_group: str = "www-data",
                          extra_env: Optional[dict[str, str]] = None) -> str:
    """Generate systemd service configuration for a Rails application."""
    env_lines = [
        'Environment="RAILS_ENV=production"',
        'Environment="RAILS_LOG_TO_STDOUT=true"',
        'Environment="RAILS_SERVE_STATIC_FILES=true"',
        f'Environment="SECRET_KEY_BASE={secret_key_base}"'
    ]
    
    if extra_env:
        for key, value in extra_env.items():
            env_lines.append(f'Environment="{key}={value}"')
            
    env_section = "\n".join(env_lines)
    
    return f"""[Unit]
Description=Rails app: {app_name}
After=network.target

[Service]
Type=simple
User={web_user}
Group={web_group}
WorkingDirectory={app_path}
{env_section}
ExecStart=/bin/bash -c 'exec bundle exec rails server -b 127.0.0.1 -p {port}'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def create_rails_service(app_name: str, app_path: str, port: int,
                        web_user: str, web_group: str,
                        env_vars: Optional[dict[str, str]] = None) -> None:
    """Create and enable a Rails systemd service."""
    service_name = f"rails-{app_name}"
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    secret_key_base = secrets.token_hex(64)
    
    # Preserve existing SECRET_KEY_BASE if service exists (read BEFORE cleanup)
    if os.path.exists(service_file):
        try:
            with open(service_file, 'r') as f:
                content = f.read()
                match = re.search(r'Environment="SECRET_KEY_BASE=([a-f0-9]+)"', content)
                if match:
                    secret_key_base = match.group(1)  # Value preserved in variable
                    print(f"  ℹ Preserving existing SECRET_KEY_BASE")
        except Exception:
            pass
    
    # Clean up existing service before creating new one
    # Note: secret_key_base is already stored in variable above
    cleanup_service(service_name)
    
    service_content = generate_rails_service(app_name, app_path, secret_key_base, port, web_user, web_group, env_vars)
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write service file {service_file}. Need root permissions.") from e
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}")
    run(f"systemctl restart {service_name}")
    
    print(f"  ✓ Created and started systemd service: {service_name}")
    
    import time
    time.sleep(1)
    
    result = run(f"systemctl is-active {service_name}", check=False)
    if result.returncode != 0:
        print(f"  ⚠ Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
    else:
        print(f"  ✓ {service_name} is running")
