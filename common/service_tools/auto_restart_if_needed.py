#!/usr/bin/env python3
"""Restart the system when updates require it and policy allows it."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from logging import ERROR
from typing import Any

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger, log_event
from lib.atomic_io import write_json_atomic
from lib.machine_state import can_restart_system, load_setup_config
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.plugin_registry import get_system_type_definition
from lib.validation import validate_filesystem_path

logger = get_service_logger('auto_restart_if_needed', 'common', use_syslog=True)

STATE_FILE = "/var/lib/infra_tools/auto_restart_state.json"
MIN_UPTIME_SECONDS = 30 * 60
NOTIFICATION_INTERVAL_SECONDS = 24 * 60 * 60


def check_restart_required() -> bool:
    """Check if system restart is required."""
    return os.path.exists("/var/run/reboot-required")


def get_uptime_seconds() -> float | None:
    """Return system uptime in seconds, or None when it cannot be read."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def get_active_sessions() -> list[str] | None:
    """Return active loginctl sessions, or None when they cannot be queried."""
    try:
        result = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _nonnegative_int(value: Any, default: int) -> int:
    """Return a policy integer, falling back for invalid persisted values."""
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


def _timestamp(value: Any, default: float) -> float:
    """Return a finite timestamp from persisted state."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def load_restart_policy() -> dict[str, Any]:
    """Load auto-restart policy from persisted setup config."""
    config = load_setup_config() or {}
    system_type = config.get("system_type")
    defaults = None
    if isinstance(system_type, str):
        defaults = get_system_type_definition(system_type)

    auto_restart = bool(config.get("auto_restart", defaults.default_auto_restart if defaults else True))
    if "auto_restart" not in config and "no_restart" in config:
        auto_restart = not bool(config.get("no_restart"))

    return {
        "auto_restart": auto_restart,
        "force_days": _nonnegative_int(
            config.get(
                "auto_restart_force_days",
                defaults.default_auto_restart_force_days if defaults else 7,
            ),
            defaults.default_auto_restart_force_days if defaults else 7,
        ),
        "grace": _nonnegative_int(config.get("auto_restart_grace", 5), 5),
    }


def load_restart_state() -> dict[str, Any]:
    """Load persistent auto-restart deferral state."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_restart_state(state: dict[str, Any]) -> None:
    """Save persistent auto-restart deferral state atomically."""
    validate_filesystem_path(STATE_FILE, must_exist=False)
    write_json_atomic(STATE_FILE, state, mode=0o600, sort_keys=True)


def clear_restart_state() -> None:
    """Remove deferral state when a restart is no longer required."""
    try:
        os.unlink(STATE_FILE)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log_event(logger, "Failed to clear restart state", level=ERROR, error=str(exc))


def should_notify(state: dict[str, Any], now: float) -> bool:
    """Return true when a deferral notification should be sent."""
    last_notified = _timestamp(state.get("last_notified"), 0)
    return last_notified > now or now - last_notified >= NOTIFICATION_INTERVAL_SECONDS


def record_deferral(reason: str, notification_configs, details: str | None = None) -> None:
    """Record a deferred restart and notify at most once per day."""
    now = time.time()
    state = load_restart_state()
    first_required = _timestamp(state.get("first_required"), now)
    state["first_required"] = now if first_required > now else first_required
    if should_notify(state, now):
        send_notification_safe(
            notification_configs,
            subject="Restart required: deferred",
            job="auto_restart_if_needed",
            status="warning",
            message=f"A restart is required, but it was deferred: {reason}.",
            details=details,
            logger=logger,
        )
        state["last_notified"] = now
    state["last_reason"] = reason
    save_restart_state(state)


def force_deadline_reached(policy: dict[str, Any]) -> bool:
    """Return true when restart deferrals have exceeded the configured max."""
    force_days = _nonnegative_int(policy.get("force_days"), 0)
    if force_days <= 0:
        return False
    state = load_restart_state()
    now = time.time()
    first_required = _timestamp(state.get("first_required"), now)
    if first_required > now:
        first_required = now
    return now - first_required >= force_days * 24 * 60 * 60


def perform_restart(notification_configs, grace_minutes: int, forced: bool = False) -> int:
    """Schedule system restart."""
    log_event(logger, "Restart required, scheduling restart", forced=forced, grace_minutes=grace_minutes)
    send_notification_safe(
        notification_configs,
        subject="Restart required: restarting soon",
        job="auto_restart_if_needed",
        status="warning",
        message=f"A restart is required. Automatic restart is scheduled in {grace_minutes} minute(s).",
        logger=logger,
    )

    try:
        shutdown_cmd = shutil.which("shutdown")
        if not shutdown_cmd:
            raise FileNotFoundError("shutdown command not found")
        subprocess.run(
            [shutdown_cmd, "-r", f"+{max(0, grace_minutes)}", "Automatic restart for system updates"],
            check=True,
        )
        return 0
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log_event(logger, "Failed to initiate restart", level=ERROR, error=str(exc))
        send_notification_safe(
            notification_configs,
            subject="Error: automatic restart failed",
            job="auto_restart_if_needed",
            status="error",
            message=f"Restart required but automatic restart failed: {exc}",
            logger=logger,
        )
        return 1


def main() -> int:
    """Check and perform restart if needed."""
    log_event(logger, "Starting restart check")
    notification_configs = load_notification_configs_from_state(logger)

    if not check_restart_required():
        clear_restart_state()
        log_event(logger, "No restart required")
        return 0

    if not can_restart_system():
        record_deferral("machine type cannot restart itself", notification_configs)
        return 0

    policy = load_restart_policy()
    uptime = get_uptime_seconds()
    if uptime is None:
        record_deferral("system uptime could not be determined", notification_configs)
        return 0
    if uptime < MIN_UPTIME_SECONDS:
        record_deferral("system booted recently", notification_configs)
        return 0

    sessions = get_active_sessions()
    if sessions is None:
        record_deferral("active sessions could not be determined", notification_configs)
        return 0
    forced = force_deadline_reached(policy)
    if not policy["auto_restart"] and not forced:
        record_deferral("automatic restarts are disabled", notification_configs)
        return 0

    if sessions and not forced:
        log_event(logger, "Active sessions detected, skipping restart")
        record_deferral("active sessions detected", notification_configs, "\n".join(sessions))
        return 0

    return perform_restart(notification_configs, int(policy["grace"]), forced=forced)


if __name__ == "__main__":
    sys.exit(main())
