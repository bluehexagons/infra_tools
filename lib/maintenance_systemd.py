"""Shared systemd provisioning for recurring maintenance jobs."""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from typing import Optional

from lib.remote_utils import is_dry_run, run
from lib.systemd_service import SYSTEMD_DIR
from lib.validation import validate_filesystem_path, validate_service_name_uniqueness
from lib.validators import validate_username


_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_unit_value(value: str, name: str) -> None:
    """Reject values that could add unintended systemd directives."""
    if not value or any(character in value for character in ("\n", "\r", "\0")):
        raise ValueError(f"{name} must be non-empty and contain no control characters")


def _escape_environment_value(value: str) -> str:
    """Escape a value for a quoted systemd Environment directive."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_unit_atomically(path: str, content: str) -> None:
    """Replace a unit file without exposing systemd to partial content."""
    validate_filesystem_path(path, must_exist=False)
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(path),
            prefix=f".{os.path.basename(path)}.",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def configure_maintenance_timer(
    *,
    service_name: str,
    service_desc: str,
    timer_desc: str,
    script_path: str,
    schedule: Optional[str],
    check_name: str,
    check_path: Optional[str] = None,
    user: Optional[str] = None,
    environment: Optional[dict[str, str]] = None,
    randomized_delay: str = "30min",
    timeout: str = "4h",
    on_boot_sec: Optional[str] = None,
    persistent: bool = True,
    network_online: bool = True,
    purpose: str = "maintenance",
) -> bool:
    """Install, enable, and verify a systemd timer for a maintenance script.

    Existing units are replaced atomically and remain enabled while their new
    definitions are staged. This avoids the maintenance gap caused by deleting
    working units before replacements have been written and loaded.
    """
    validate_service_name_uniqueness(service_name, [])
    validate_filesystem_path(script_path, must_exist=False)
    if not os.path.isabs(script_path):
        raise ValueError(f"Maintenance script path must be absolute: {script_path}")

    for value, name in (
        (service_desc, "service description"),
        (timer_desc, "timer description"),
        (check_name, "maintenance name"),
        (randomized_delay, "randomized delay"),
        (timeout, "service timeout"),
        (purpose, "maintenance purpose"),
    ):
        _validate_unit_value(value, name)
    if schedule:
        _validate_unit_value(schedule, "timer schedule")
    if on_boot_sec:
        _validate_unit_value(on_boot_sec, "boot delay")
    if not schedule and not on_boot_sec:
        raise ValueError("Maintenance timer requires a calendar or boot trigger")

    if check_path:
        validate_filesystem_path(check_path, must_exist=False)
        if not os.path.isabs(check_path):
            raise ValueError(f"Maintenance prerequisite path must be absolute: {check_path}")
        if not os.path.exists(check_path):
            print(f"  ℹ {check_name} not installed, skipping {purpose} configuration")
            return True

    user_line = ""
    if user:
        if not validate_username(user):
            raise ValueError(f"Invalid service username: {user}")
        user_line = f"User={user}\n"

    environment_lines = ""
    for name, value in sorted((environment or {}).items()):
        if not _ENVIRONMENT_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name}")
        _validate_unit_value(value, f"environment variable {name}")
        environment_lines += f'Environment="{name}={_escape_environment_value(value)}"\n'

    service_file = os.path.join(SYSTEMD_DIR, f"{service_name}.service")
    timer_file = os.path.join(SYSTEMD_DIR, f"{service_name}.timer")
    network_lines = "Wants=network-online.target\nAfter=network-online.target\n" if network_online else ""
    service_content = f"""[Unit]
Description={service_desc}
Documentation=man:systemd.service(5)
{network_lines}

[Service]
Type=oneshot
{user_line}{environment_lines}ExecStart=/usr/bin/python3 {shlex.quote(script_path)}
TimeoutStartSec={timeout}
StandardOutput=journal
StandardError=journal
"""
    trigger_lines = ""
    if on_boot_sec:
        trigger_lines += f"OnBootSec={on_boot_sec}\n"
    if schedule:
        trigger_lines += f"OnCalendar={schedule}\n"
    if persistent and schedule:
        trigger_lines += "Persistent=true\n"
    timer_content = f"""[Unit]
Description={timer_desc}
Documentation=man:systemd.timer(5)

[Timer]
{trigger_lines}AccuracySec=1min
RandomizedDelaySec={randomized_delay}

[Install]
WantedBy=timers.target
"""

    if is_dry_run():
        print(f"  [DRY-RUN] Would configure {check_name} {purpose} timer")
        return True

    _write_unit_atomically(service_file, service_content)
    _write_unit_atomically(timer_file, timer_content)

    timer_unit = f"{service_name}.timer"
    reload_result = run("systemctl daemon-reload", check=False)
    if reload_result.returncode != 0:
        print(f"  ⚠ {check_name} {purpose} units written but systemd could not reload")
        return False

    enable_result = run(f"systemctl enable {shlex.quote(timer_unit)}", check=False)
    if enable_result.returncode != 0:
        print(f"  ⚠ {check_name} {purpose} timer could not be enabled")
        return False

    start_result = run(f"systemctl start {shlex.quote(timer_unit)}", check=False)
    if start_result.returncode != 0:
        print(f"  ⚠ {check_name} {purpose} timer could not be started")
        return False

    enabled_result = run(f"systemctl is-enabled {shlex.quote(timer_unit)}", check=False)
    active_result = run(f"systemctl is-active {shlex.quote(timer_unit)}", check=False)
    if enabled_result.returncode != 0 or active_result.returncode != 0:
        print(f"  ⚠ {check_name} {purpose} timer failed post-install verification")
        return False

    trigger_summary = schedule or f"after boot: {on_boot_sec}"
    print(f"  ✓ {check_name} {purpose} configured ({trigger_summary})")
    return True
