#!/usr/bin/env python3
"""Restart the system when updates require it and policy allows it."""

from __future__ import annotations

import json
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
from lib.machine_state import can_restart_system, load_setup_config
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.plugin_registry import get_system_type_definition

logger = get_service_logger('auto_restart_if_needed', 'common', use_syslog=True)

STATE_FILE = "/var/lib/infra_tools/auto_restart_state.json"
MIN_UPTIME_SECONDS = 30 * 60
NOTIFICATION_INTERVAL_SECONDS = 24 * 60 * 60


def check_restart_required() -> bool:
    """Check if system restart is required."""
    return os.path.exists("/var/run/reboot-required")


def get_uptime_seconds() -> float:
    """Return system uptime in seconds."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def get_active_sessions() -> list[str]:
    """Return active loginctl sessions."""
    try:
        result = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


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
        "force_days": int(config.get("auto_restart_force_days", defaults.default_auto_restart_force_days if defaults else 7)),
        "grace": int(config.get("auto_restart_grace", 5)),
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
    state_dir = os.path.dirname(STATE_FILE)
    os.makedirs(state_dir, exist_ok=True)
    tmp_file = f"{STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_file, STATE_FILE)


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
    last_notified = float(state.get("last_notified", 0) or 0)
    return now - last_notified >= NOTIFICATION_INTERVAL_SECONDS


def record_deferral(reason: str, notification_configs, details: str | None = None) -> None:
    """Record a deferred restart and notify at most once per day."""
    now = time.time()
    state = load_restart_state()
    state.setdefault("first_required", now)
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
    force_days = int(policy["force_days"])
    if force_days <= 0:
        return False
    state = load_restart_state()
    first_required_value = state.get("first_required")
    first_required = float(first_required_value) if first_required_value is not None else time.time()
    return time.time() - first_required >= force_days * 24 * 60 * 60


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
    if uptime and uptime < MIN_UPTIME_SECONDS:
        record_deferral("system booted recently", notification_configs)
        return 0

    sessions = get_active_sessions()
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
