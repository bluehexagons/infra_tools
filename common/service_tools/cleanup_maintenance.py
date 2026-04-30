#!/usr/bin/env python3
"""Clean up temporary files, journals, and package caches."""

from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess
import sys
import time
from logging import ERROR, INFO, WARNING, DEBUG

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.disk_utils import get_disk_usage_details
from lib.logging_utils import get_service_logger, log_event
from lib.maintenance_defaults import (
    APT_LOCK_OPTIONS,
    CLEANUP_COMMAND_TIMEOUT_SECONDS,
    INFRA_TMP_DIRS,
    INFRA_TMP_PREFIXES,
    JOURNAL_MAX_USE,
    STALE_INFRA_TMP_MAX_AGE_DAYS,
)
from lib.notifications import load_notification_configs_from_state, send_notification_safe


logger = get_service_logger('cleanup_maintenance', 'common', use_syslog=True)


def run_command(
    command: list[str],
    env: dict[str, str] | None = None,
    timeout: int = CLEANUP_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output."""
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=timeout)


def run_cleanup_command(
    command: list[str],
    action: str,
    env: dict[str, str] | None = None,
) -> str | None:
    """Run a cleanup command and return a failure summary when it fails."""
    try:
        result = run_command(command, env=env)
    except subprocess.TimeoutExpired:
        details = f"timed out after {CLEANUP_COMMAND_TIMEOUT_SECONDS}s"
        log_event(logger, f"{action} timed out", level=WARNING, stderr=details)
        return f"{action}: {details}"

    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"{action} failed"
        log_event(logger, f"{action} failed", level=WARNING, stderr=details)
        return f"{action}: {details}"

    log_event(logger, f"{action} completed", level=INFO)
    return None


def cleanup_apt_cache() -> list[str]:
    """Clean APT package caches when apt-get is available."""
    apt_get = shutil.which("apt-get")
    if not apt_get:
        log_event(logger, "apt-get not found, skipping APT cache cleanup")
        return []

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    failures: list[str] = []
    for command, action in (
        ([apt_get, "autoclean", "-qq"] + APT_LOCK_OPTIONS, "APT autoclean"),
        ([apt_get, "autoremove", "-y", "-qq"] + APT_LOCK_OPTIONS, "APT autoremove"),
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

    log_event(logger, f"{action} not available, skipping")
    return None


def cleanup_stale_infra_tmp_artifacts(
    tmp_dir: str = "/tmp",
    max_age_days: int = STALE_INFRA_TMP_MAX_AGE_DAYS,
) -> list[str]:
    """Remove stale infra_tools temp files/directories left by interrupted runs."""
    failures: list[str] = []
    try:
        names = os.listdir(tmp_dir)
    except FileNotFoundError:
        return []
    except OSError as exc:
        details = str(exc)
        log_event(
            logger,
            "Failed to list infra_tools temp artifacts",
            level=WARNING,
            tmp_dir=tmp_dir,
            error=details,
        )
        return [f"infra temp cleanup: {details}"]

    cutoff = time.time() - (max_age_days * 24 * 60 * 60)
    removed: list[str] = []
    for name in names:
        if not name.startswith(INFRA_TMP_PREFIXES):
            continue
        path = os.path.join(tmp_dir, name)
        try:
            stat_result = os.lstat(path)
            if stat_result.st_mtime > cutoff:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
            removed.append(name)
        except OSError as exc:
            details = str(exc)
            log_event(
                logger,
                "Failed to remove infra_tools temp artifact",
                level=WARNING,
                path=path,
                error=details,
            )
            failures.append(f"{path}: {details}")

    if removed:
        log_event(
            logger,
            "Removed stale infra_tools temp artifacts",
            tmp_dir=tmp_dir,
            max_age_days=max_age_days,
            removed_count=len(removed),
            removed_names=",".join(sorted(removed)),
        )
    return failures


def run_nvm_command(nvm_dir: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an nvm command in the requested NVM directory."""
    full_cmd = (
        f'export NVM_DIR={shlex.quote(nvm_dir)} && '
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
        f'{shlex.join(args)}'
    )
    return subprocess.run(
        ["/bin/bash", "-lc", full_cmd],
        capture_output=True,
        text=True,
        timeout=CLEANUP_COMMAND_TIMEOUT_SECONDS,
    )


def iter_nvm_dirs() -> list[tuple[str, str]]:
    """Return installed user NVM directories."""
    nvm_dirs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for entry in pwd.getpwall():
        home_dir = entry.pw_dir
        if not home_dir or home_dir in seen:
            continue
        nvm_dir = os.path.join(home_dir, ".nvm")
        if os.path.isdir(nvm_dir):
            seen.add(home_dir)
            nvm_dirs.append((entry.pw_name, nvm_dir))

    return nvm_dirs


def cleanup_old_node_versions() -> list[str]:
    """Remove stale nvm-managed Node.js versions while preserving the default one."""
    failures: list[str] = []

    for username, nvm_dir in iter_nvm_dirs():
        try:
            default_result = run_nvm_command(nvm_dir, ["nvm", "version", "default"])
        except subprocess.TimeoutExpired:
            details = f"nvm version default timed out after {CLEANUP_COMMAND_TIMEOUT_SECONDS}s"
            log_event(
                logger,
                "Skipping nvm version cleanup",
                level=WARNING,
                username=username,
                nvm_dir=nvm_dir,
                reason=details,
            )
            failures.append(f"{username} default: {details}")
            continue
        current_version = default_result.stdout.strip()
        if default_result.returncode != 0 or not current_version or current_version == "N/A":
            log_event(
                logger,
                "Skipping nvm version cleanup",
                level=WARNING,
                username=username,
                nvm_dir=nvm_dir,
                reason="default version unavailable",
            )
            continue

        versions_dir = os.path.join(nvm_dir, "versions", "node")
        if not os.path.isdir(versions_dir):
            continue

        removed_versions: list[str] = []
        for version_name in os.listdir(versions_dir):
            version_dir = os.path.join(versions_dir, version_name)
            if version_name == current_version or not version_name.startswith("v"):
                continue
            if not os.path.isdir(version_dir):
                continue

            try:
                shutil.rmtree(version_dir)
                removed_versions.append(version_name)
            except OSError as exc:
                details = str(exc)
                log_event(
                    logger,
                    "Failed to remove old Node.js version",
                    level=WARNING,
                    username=username,
                    nvm_dir=nvm_dir,
                    version=version_name,
                    error=details,
                )
                failures.append(f"{username} {version_name}: {details}")

        try:
            cache_result = run_nvm_command(nvm_dir, ["nvm", "cache", "clear"])
        except subprocess.TimeoutExpired:
            details = f"nvm cache clear timed out after {CLEANUP_COMMAND_TIMEOUT_SECONDS}s"
            log_event(
                logger,
                "nvm cache cleanup timed out",
                level=WARNING,
                username=username,
                nvm_dir=nvm_dir,
                error=details,
            )
            failures.append(f"{username} cache: {details}")
            continue
        if cache_result.returncode != 0:
            details = cache_result.stderr.strip() or cache_result.stdout.strip() or "nvm cache clear failed"
            log_event(
                logger,
                "nvm cache cleanup failed",
                level=WARNING,
                username=username,
                nvm_dir=nvm_dir,
                error=details,
            )
            failures.append(f"{username} cache: {details}")
        elif removed_versions:
            log_event(
                logger,
                "Removed old Node.js versions",
                username=username,
                nvm_dir=nvm_dir,
                kept_version=current_version,
                removed_versions=",".join(removed_versions),
            )

    return failures


def log_tmp_usage(tmp_dir: str = "/tmp") -> None:
    """Log current disk usage for a temporary directory."""
    try:
        usage = shutil.disk_usage(tmp_dir)
        total_mb = usage.total // (1024 * 1024)
        used_mb = (usage.total - usage.free) // (1024 * 1024)
        free_mb = usage.free // (1024 * 1024)
        usage_percent = round((used_mb / total_mb * 100) if total_mb else 0, 1)
        log_event(
            logger,
            "Temp directory usage",
            level=DEBUG,
            tmp_dir=tmp_dir,
            total_mb=total_mb,
            used_mb=used_mb,
            free_mb=free_mb,
            usage_percent=usage_percent,
        )
    except OSError as exc:
        log_event(
            logger,
            "Could not read temp directory usage",
            level=WARNING,
            tmp_dir=tmp_dir,
            error=str(exc),
        )


def notify_if_storage_still_low(notification_configs) -> None:
    """Notify when the root filesystem remains crowded after cleanup."""
    usage = get_disk_usage_details("/")
    usage_percent = usage.get("usage_percent", 0)
    if usage_percent < 80:
        return

    status = "error" if usage_percent >= 90 else "warning"
    subject = (
        "Error: storage still low after cleanup"
        if status == "error"
        else "Warning: storage still low after cleanup"
    )
    message = f"Root filesystem usage remains at {usage_percent}% after cleanup"
    details = (
        f"Total: {usage.get('total_mb', 0)} MB\n"
        f"Used: {usage.get('used_mb', 0)} MB\n"
        f"Free: {usage.get('free_mb', 0)} MB\n"
        f"Usage: {usage_percent}%"
    )

    log_event(
        logger,
        "Storage remains low after cleanup",
        level=ERROR if status == "error" else WARNING,
        usage_percent=usage_percent,
        free_mb=usage.get("free_mb", 0),
    )
    send_notification_safe(
        notification_configs,
        subject=subject,
        job="cleanup_maintenance",
        status=status,
        message=message,
        details=details,
        logger=logger,
    )


def main() -> int:
    """Run system cleanup tasks and notify on failures."""
    log_event(logger, "Starting cleanup maintenance")
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

    for tmp_dir in INFRA_TMP_DIRS:
        log_tmp_usage(tmp_dir)
        failures.extend(cleanup_stale_infra_tmp_artifacts(tmp_dir=tmp_dir))
    failures.extend(cleanup_old_node_versions())
    notify_if_storage_still_low(notification_configs)

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

    log_event(logger, "Cleanup maintenance completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
