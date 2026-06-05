#!/usr/bin/env python3
"""
Auto-update Gogs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from logging import ERROR

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger, log_event
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from web.gogs_steps import (
    GOGS_BINARY_LINK,
    GOGS_SERVICE,
    build_gogs_admin_command,
    install_or_update_gogs_release,
    read_gogs_state,
    write_gogs_state,
)


logger = get_service_logger('auto_update_gogs', 'common', use_syslog=True)


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def _run_shell_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/bin/bash", "-lc", command], capture_output=True, text=True)


def _derive_data_path(config_path: str) -> str | None:
    suffix = "/custom/conf/app.ini"
    if config_path.endswith(suffix):
        return config_path[:-len(suffix)]
    return None


def main() -> int:
    """Update Gogs to the preferred upstream release when installed."""
    notification_configs = load_notification_configs_from_state(logger)
    state = read_gogs_state()
    config_path = state.get("config_path")
    installed_tag = state.get("tag_name")

    if not isinstance(config_path, str) or not config_path or not os.path.exists(config_path):
        log_event(logger, "Gogs config not found, skipping update")
        return 0

    if not os.path.exists(GOGS_BINARY_LINK):
        log_event(logger, "Gogs binary not found, skipping update")
        return 0

    log_event(logger, "Starting Gogs update check", current_version=installed_tag or "unknown")
    try:
        target_tag, changed = install_or_update_gogs_release()
    except Exception as exc:
        details = str(exc)
        log_event(logger, "Gogs release update failed", level=ERROR, stderr=details)
        send_notification_safe(
            notification_configs,
            subject="Error: Gogs update failed",
            job="auto_update_gogs",
            status="error",
            message="Failed to install the preferred Gogs release",
            details=details,
            logger=logger,
        )
        return 1

    if not changed:
        log_event(
            logger,
            "Gogs already up to date",
            current_version=installed_tag or target_tag,
            target_version=target_tag,
        )
        return 0

    data_path = state.get("data_path")
    if not isinstance(data_path, str) or not data_path:
        data_path = _derive_data_path(config_path)
    if not data_path:
        details = f"Missing Gogs data path for config {config_path}"
        log_event(logger, "Gogs state update failed", level=ERROR, stderr=details)
        send_notification_safe(
            notification_configs,
            subject="Error: Gogs update failed",
            job="auto_update_gogs",
            status="error",
            message="Updated Gogs but could not persist updated install state",
            details=details,
            logger=logger,
        )
        return 1
    write_gogs_state(target_tag, data_path, config_path)

    for admin_args, label in (
        (["admin", "rewrite-authorized-keys"], "authorized_keys"),
        (["admin", "resync-hooks"], "repository hooks"),
    ):
        result = _run_shell_command(build_gogs_admin_command(admin_args, config_path))
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or f"Failed to refresh {label}"
            log_event(logger, "Gogs post-update command failed", level=ERROR, step=label, stderr=details)
            send_notification_safe(
                notification_configs,
                subject="Error: Gogs update failed",
                job="auto_update_gogs",
                status="error",
                message=f"Failed to refresh Gogs {label} after updating",
                details=details,
                logger=logger,
            )
            return 1

    restart_result = _run_command(["systemctl", "restart", GOGS_SERVICE])
    if restart_result.returncode != 0:
        details = restart_result.stderr.strip() or restart_result.stdout.strip() or "systemctl restart failed"
        log_event(logger, "Gogs service restart failed", level=ERROR, stderr=details)
        send_notification_safe(
            notification_configs,
            subject="Error: Gogs update failed",
            job="auto_update_gogs",
            status="error",
            message="Updated Gogs but failed to restart the service",
            details=details,
            logger=logger,
        )
        return 1

    log_event(
        logger,
        "Gogs updated successfully",
        current_version=installed_tag or "unknown",
        target_version=target_tag,
    )
    send_notification_safe(
        notification_configs,
        subject="Success: Gogs updated",
        job="auto_update_gogs",
        status="success",
        message=f"Gogs updated to {target_tag}",
        logger=logger,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
