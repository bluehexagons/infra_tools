#!/usr/bin/env python3
"""Update a managed HomeBox service through its recovery-aware transaction."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from logging import ERROR

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

from lib.atomic_io import write_json_atomic
from lib.logging_utils import get_service_logger, log_event
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from web.homebox_steps import UPDATE_STATE, update_homebox_to_latest


logger = get_service_logger("auto_update_homebox", "common", use_syslog=True)


def _record_update_result(
    exit_code: int,
    version: str | None,
    changed: bool,
) -> None:
    """Persist a non-secret result for the HomeBox health command."""
    value: dict[str, object] = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "successful": exit_code == 0,
        "changed": changed,
    }
    if version:
        value["version"] = version
    write_json_atomic(str(UPDATE_STATE), value, mode=0o600, sort_keys=True)


def _run_update() -> tuple[int, str | None, bool]:
    """Run one safe release check and report its exit status and outcome."""
    notification_configs = load_notification_configs_from_state(logger)
    try:
        outcome = update_homebox_to_latest()
    except Exception as exc:
        details = str(exc)
        log_event(logger, "HomeBox update failed", level=ERROR, stderr=details)
        send_notification_safe(
            notification_configs,
            subject="Error: HomeBox update failed",
            job="auto_update_homebox",
            status="error",
            message="HomeBox could not complete its scheduled update",
            details=details,
            logger=logger,
        )
        return 1, None, False

    if outcome is None or not outcome[0]:
        log_event(logger, "HomeBox is not enabled, skipping update")
        return 0, None, False

    version, changed = outcome
    if not changed:
        log_event(logger, "HomeBox already up to date", target_version=version)
        return 0, version, False

    log_event(logger, "HomeBox updated successfully", target_version=version)
    send_notification_safe(
        notification_configs,
        subject="Success: HomeBox updated",
        job="auto_update_homebox",
        status="good",
        message=f"HomeBox updated to {version}",
        logger=logger,
    )
    return 0, version, True


def main() -> int:
    """Run and record one recurring HomeBox update check."""
    exit_code = 1
    version: str | None = None
    changed = False
    try:
        exit_code, version, changed = _run_update()
        return exit_code
    finally:
        _record_update_result(exit_code, version, changed)


if __name__ == "__main__":
    raise SystemExit(main())
