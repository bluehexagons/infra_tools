#!/usr/bin/env python3
"""Clean up temporary files, journals, and package caches."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.maintenance_defaults import APT_LOCK_OPTIONS, JOURNAL_MAX_USE
from lib.notifications import load_notification_configs_from_state, send_notification_safe


logger = get_service_logger('cleanup_maintenance', 'common', use_syslog=True)


def run_command(
    command: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output."""
    return subprocess.run(command, capture_output=True, text=True, env=env)


def run_cleanup_command(
    command: list[str],
    action: str,
    env: dict[str, str] | None = None,
) -> str | None:
    """Run a cleanup command and return a failure summary when it fails."""
    result = run_command(command, env=env)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"{action} failed"
        logger.warning("%s failed: %s", action, details)
        return f"{action}: {details}"

    logger.info("%s completed", action)
    return None


def cleanup_apt_cache() -> list[str]:
    """Clean APT package caches when apt-get is available."""
    apt_get = shutil.which("apt-get")
    if not apt_get:
        logger.info("apt-get not found, skipping APT cache cleanup")
        return []

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    failures: list[str] = []
    for command, action in (
        ([apt_get, "autoclean", "-qq"] + APT_LOCK_OPTIONS, "APT autoclean"),
        ([apt_get, "clean"] + APT_LOCK_OPTIONS, "APT clean"),
    ):
        failure = run_cleanup_command(command, action, env=env)
        if failure:
            failures.append(failure)
    return failures


def cleanup_optional_cache(
    executable_names: list[str],
    args: list[str],
    action: str,
) -> str | None:
    """Run an optional cache cleanup command when its executable is installed."""
    for executable_name in executable_names:
        executable_path = shutil.which(executable_name)
        if executable_path:
            return run_cleanup_command([executable_path] + args, action)

    logger.info("%s not available, skipping", action)
    return None


def main() -> int:
    """Run system cleanup tasks and notify on failures."""
    logger.info("Starting cleanup maintenance")
    notification_configs = load_notification_configs_from_state(logger)

    failures = cleanup_apt_cache()

    for failure in (
        cleanup_optional_cache(["systemd-tmpfiles"], ["--clean"], "systemd tmpfiles cleanup"),
        cleanup_optional_cache(["journalctl"], [f"--vacuum-size={JOURNAL_MAX_USE}"], "journal vacuum"),
        cleanup_optional_cache(["npm"], ["cache", "clean", "--force"], "npm cache cleanup"),
        cleanup_optional_cache(["pip3", "pip"], ["cache", "purge"], "pip cache cleanup"),
        cleanup_optional_cache(["gem"], ["cleanup"], "gem cleanup"),
        cleanup_optional_cache(["uv"], ["cache", "clean"], "uv cache cleanup"),
    ):
        if failure:
            failures.append(failure)

    if failures:
        send_notification_safe(
            notification_configs,
            subject="Error: cleanup maintenance failed",
            job="cleanup_maintenance",
            status="error",
            message="One or more cleanup maintenance tasks failed",
            details="\n".join(failures),
            logger=logger,
        )
        return 1

    logger.info("Cleanup maintenance completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
