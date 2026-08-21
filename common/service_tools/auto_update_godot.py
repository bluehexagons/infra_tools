#!/usr/bin/env python3
"""Auto-update the verified official Godot Engine release."""

from __future__ import annotations

import os
import sys
from logging import ERROR

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

from common.godot_steps import (
    GODOT_BINARY_LINK,
    install_or_update_godot_release,
    update_registered_godot_bundles,
)
from lib.logging_utils import get_service_logger, log_event
from lib.notifications import load_notification_configs_from_state, send_notification_safe


logger = get_service_logger("auto_update_godot", "common", use_syslog=True)


def main() -> int:
    """Update Godot to the newest stable release when it is installed."""
    notification_configs = load_notification_configs_from_state(logger)
    if not os.path.exists(GODOT_BINARY_LINK):
        log_event(logger, "Godot not found, skipping update")
        return 0

    try:
        tag_name, engine_changed, _archive_sha256 = install_or_update_godot_release()
        bundle_changed = update_registered_godot_bundles()
    except Exception as exc:
        details = str(exc)
        log_event(logger, "Godot update failed", level=ERROR, stderr=details)
        send_notification_safe(
            notification_configs,
            subject="Error: Godot update failed",
            job="auto_update_godot",
            status="error",
            message="Failed to install the latest stable Godot release",
            details=details,
            logger=logger,
        )
        return 1

    if not engine_changed and not bundle_changed:
        log_event(logger, "Godot tooling already up to date", target_version=tag_name)
        return 0

    log_event(logger, "Godot tooling updated successfully", target_version=tag_name)
    send_notification_safe(
        notification_configs,
        subject="Success: Godot updated",
        job="auto_update_godot",
        status="success",
        message=f"Godot tooling updated to {tag_name}",
        logger=logger,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
