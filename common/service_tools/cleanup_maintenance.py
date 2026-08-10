#!/usr/bin/env python3
"""Run bounded system cleanup and post-cleanup capacity checks."""

from __future__ import annotations

import json
import os
import re
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
    CRASH_REPORT_DIRS,
    CRASH_REPORT_PATTERNS,
    INFRA_TMP_DIRS,
    INFRA_TMP_PATTERNS,
    JOURNAL_MAX_AGE,
    JOURNAL_MAX_USE,
    STALE_CRASH_REPORT_MAX_AGE_DAYS,
    STALE_INFRA_TMP_MAX_AGE_DAYS,
    STORAGE_CRITICAL_PERCENT,
    STORAGE_WARNING_PERCENT,
)
from lib.machine_state import is_container
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.types import JSONDict
from lib.validation import validate_filesystem_path, validate_positive_integer


logger = get_service_logger('cleanup_maintenance', 'common', use_syslog=True)
_INFRA_TMP_RE = re.compile(rf"^(?:{'|'.join(INFRA_TMP_PATTERNS)})$")
_CRASH_REPORT_RE = re.compile(rf"^(?:{'|'.join(CRASH_REPORT_PATTERNS)})$")
_REMOTE_FILESYSTEM_TYPES = {
    "9p",
    "ceph",
    "cifs",
    "glusterfs",
    "nfs",
    "nfs4",
    "smb3",
    "sshfs",
}


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
    except OSError as exc:
        details = str(exc)
        log_event(logger, f"{action} could not run", level=WARNING, stderr=details)
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
        ([apt_get, "clean"] + APT_LOCK_OPTIONS, "APT clean"),
    ):
        failure = run_cleanup_command(command, action, env=env)
        if failure:
            failures.append(failure)
    return failures


def cleanup_unused_packages() -> list[str]:
    """Purge packages APT marks unused and residual package configuration.

    APT's configured kernel-retention policy protects kernels it considers
    required.
    """
    apt_get = shutil.which("apt-get")
    if not apt_get:
        log_event(logger, "apt-get not found, skipping unused package cleanup")
        return []

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    failures: list[str] = []
    for command, action in (
        (
            [apt_get, "autoremove", "--purge", "-y", "-qq"] + APT_LOCK_OPTIONS,
            "APT unused package cleanup",
        ),
        (
            [apt_get, "purge", "-y", "-qq", "~c"] + APT_LOCK_OPTIONS,
            "APT residual configuration cleanup",
        ),
    ):
        failure = run_cleanup_command(command, action, env=env)
        if failure:
            failures.append(failure)
    return failures


def audit_package_database() -> str | None:
    """Report incomplete or inconsistent dpkg package state without repairing it."""
    dpkg = shutil.which("dpkg")
    if not dpkg:
        log_event(logger, "dpkg not found, skipping package database audit")
        return None

    try:
        result = run_command([dpkg, "--audit"], timeout=60)
    except subprocess.TimeoutExpired:
        details = "timed out after 60s"
        log_event(logger, "Package database audit timed out", level=WARNING, error=details)
        return f"package database audit: {details}"
    except OSError as exc:
        details = str(exc)
        log_event(logger, "Package database audit could not run", level=WARNING, error=details)
        return f"package database audit: {details}"

    details = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0 or details:
        details = details or f"dpkg exited {result.returncode}"
        log_event(logger, "Package database audit found issues", level=WARNING, error=details)
        return f"package database audit: {details}"

    log_event(logger, "Package database audit completed", level=INFO)
    return None


def run_optional_cleanup(
    executable_names: list[str],
    args: list[str],
    action: str,
) -> str | None:
    """Run an optional cleanup command when its executable is installed."""
    for executable_name in executable_names:
        executable_path = shutil.which(executable_name)
        if executable_path:
            return run_cleanup_command([executable_path] + args, action)

    log_event(logger, f"{action} not available, skipping")
    return None


def cleanup_filesystem_free_space() -> str | None:
    """Return unused blocks to storage on hosts that own their filesystems."""
    if is_container():
        log_event(logger, "Skipping filesystem trim inside container")
        return None

    systemctl = shutil.which("systemctl")
    if systemctl:
        try:
            timer_status = run_command(
                [systemctl, "is-active", "--quiet", "fstrim.timer"],
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log_event(
                logger,
                "Could not inspect native filesystem trim timer",
                level=WARNING,
                error=str(exc),
            )
        else:
            if timer_status.returncode == 0:
                log_event(logger, "Native filesystem trim timer is active, skipping fallback trim")
                return None

    return run_optional_cleanup(
        ["fstrim"],
        ["--all", "--verbose", "--quiet-unsupported"],
        "filesystem trim",
    )


def cleanup_stale_crash_reports(
    crash_dir: str = "/var/crash",
    max_age_days: int = STALE_CRASH_REPORT_MAX_AGE_DAYS,
) -> list[str]:
    """Remove recognized regular crash-report files after the retention window."""
    validate_filesystem_path(crash_dir, must_exist=False)
    max_age_days = validate_positive_integer(str(max_age_days), "max age days")
    try:
        entries = list(os.scandir(crash_dir))
    except FileNotFoundError:
        return []
    except OSError as exc:
        details = str(exc)
        log_event(
            logger,
            "Failed to list crash reports",
            level=WARNING,
            crash_dir=crash_dir,
            error=details,
        )
        return [f"crash report cleanup: {details}"]

    cutoff = time.time() - (max_age_days * 24 * 60 * 60)
    failures: list[str] = []
    removed_count = 0
    for entry in entries:
        if not _CRASH_REPORT_RE.fullmatch(entry.name):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                continue
            os.unlink(entry.path)
            removed_count += 1
        except OSError as exc:
            details = str(exc)
            log_event(
                logger,
                "Failed to remove stale crash report",
                level=WARNING,
                path=entry.path,
                error=details,
            )
            failures.append(f"{entry.path}: {details}")

    if removed_count:
        log_event(
            logger,
            "Removed stale crash reports",
            crash_dir=crash_dir,
            max_age_days=max_age_days,
            removed_count=removed_count,
        )
    return failures


def cleanup_stale_infra_tmp_artifacts(
    tmp_dir: str = "/tmp",
    max_age_days: int = STALE_INFRA_TMP_MAX_AGE_DAYS,
) -> list[str]:
    """Remove stale infra_tools temp files/directories left by interrupted runs."""
    validate_filesystem_path(tmp_dir, must_exist=False)
    max_age_days = validate_positive_integer(str(max_age_days), "max age days")
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
        if not _INFRA_TMP_RE.fullmatch(name):
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


def discover_local_mount_points() -> list[str]:
    """Return validated real filesystem mount points, falling back to root."""
    findmnt = shutil.which("findmnt")
    if not findmnt:
        log_event(logger, "findmnt not found, checking root filesystem only")
        return ["/"]

    try:
        result = run_command(
            [findmnt, "--json", "--real", "--output", "TARGET,FSTYPE"],
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log_event(
            logger,
            "Could not discover local filesystems, checking root only",
            level=WARNING,
            error=str(exc),
        )
        return ["/"]

    if result.returncode != 0:
        details = result.stderr.strip() or f"findmnt exited {result.returncode}"
        log_event(
            logger,
            "Could not discover local filesystems, checking root only",
            level=WARNING,
            error=details,
        )
        return ["/"]

    try:
        document: JSONDict = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        log_event(
            logger,
            "Could not parse local filesystem inventory, checking root only",
            level=WARNING,
        )
        return ["/"]
    if not isinstance(document, dict):
        log_event(
            logger,
            "Invalid local filesystem inventory, checking root only",
            level=WARNING,
        )
        return ["/"]

    targets: set[str] = {"/"}

    def collect_targets(nodes: object) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            target = node.get("target")
            filesystem_type = node.get("fstype")
            is_remote = (
                isinstance(filesystem_type, str)
                and (
                    filesystem_type in _REMOTE_FILESYSTEM_TYPES
                    or filesystem_type.startswith("fuse.")
                )
            )
            if isinstance(target, str) and os.path.isabs(target) and not is_remote:
                try:
                    validate_filesystem_path(target, must_exist=True)
                except ValueError:
                    log_event(
                        logger,
                        "Skipping invalid filesystem mount point",
                        level=WARNING,
                        target=target,
                    )
                else:
                    targets.add(target)
            collect_targets(node.get("children"))

    collect_targets(document.get("filesystems"))
    return sorted(targets, key=lambda target: (target != "/", target.count("/"), target))


def collect_local_storage_usage() -> dict[str, dict[str, int]]:
    """Collect block and inode usage once per real local filesystem."""
    usage_by_mount: dict[str, dict[str, int]] = {}
    seen_filesystems: set[tuple[int, int, int, int]] = set()
    for mount_point in discover_local_mount_points():
        usage = get_disk_usage_details(mount_point)
        if usage.get("total_mb", 0) <= 0:
            continue
        try:
            stat_result = os.stat(mount_point)
            filesystem_stats = os.statvfs(mount_point)
        except OSError as exc:
            log_event(
                logger,
                "Could not inspect local filesystem usage",
                level=WARNING,
                mount_point=mount_point,
                error=str(exc),
            )
            continue

        inode_total = filesystem_stats.f_files
        inode_used = max(0, inode_total - filesystem_stats.f_ffree)
        usage["inode_usage_percent"] = (
            int((inode_used / inode_total) * 100) if inode_total > 0 else 0
        )
        signature = (
            stat_result.st_dev,
            usage.get("total_mb", 0),
            usage.get("used_mb", 0),
            usage.get("free_mb", 0),
        )
        if signature in seen_filesystems:
            continue
        seen_filesystems.add(signature)
        usage_by_mount[mount_point] = usage
    return usage_by_mount


def notify_if_storage_still_low(notification_configs) -> None:
    """Notify when any local filesystem remains crowded after cleanup."""
    usage_by_mount = collect_local_storage_usage()
    crowded = {
        mount_point: usage
        for mount_point, usage in usage_by_mount.items()
        if usage.get("usage_percent", 0) >= STORAGE_WARNING_PERCENT
        or usage.get("inode_usage_percent", 0) >= STORAGE_WARNING_PERCENT
    }
    if not crowded:
        return

    critical = any(
        usage.get("usage_percent", 0) >= STORAGE_CRITICAL_PERCENT
        or usage.get("inode_usage_percent", 0) >= STORAGE_CRITICAL_PERCENT
        for usage in crowded.values()
    )
    status = "error" if critical else "warning"
    subject = (
        "Error: storage still low after cleanup"
        if status == "error"
        else "Warning: storage still low after cleanup"
    )
    message = (
        f"{len(crowded)} local filesystem(s) remain above storage thresholds after cleanup"
    )
    detail_lines = []
    for mount_point, usage in crowded.items():
        detail_lines.append(
            f"{mount_point}: space={usage.get('usage_percent', 0)}%, "
            f"inodes={usage.get('inode_usage_percent', 0)}%, "
            f"free={usage.get('free_mb', 0)} MB, total={usage.get('total_mb', 0)} MB"
        )
    details = "\n".join(detail_lines)

    log_event(
        logger,
        "Storage remains low after cleanup",
        level=ERROR if status == "error" else WARNING,
        affected_mounts=len(crowded),
        critical=critical,
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
    failures.extend(cleanup_unused_packages())
    package_audit_failure = audit_package_database()
    if package_audit_failure:
        failures.append(package_audit_failure)

    for failure in (
        run_optional_cleanup(["systemd-tmpfiles"], ["--clean"], "systemd tmpfiles cleanup"),
        run_optional_cleanup(
            ["journalctl"],
            [
                "--rotate",
                f"--vacuum-size={JOURNAL_MAX_USE}",
                f"--vacuum-time={JOURNAL_MAX_AGE}",
            ],
            "journal rotation and vacuum",
        ),
        run_optional_cleanup(["logrotate"], ["/etc/logrotate.conf"], "log rotation"),
        run_optional_cleanup(["npm"], ["cache", "clean", "--force"], "npm cache cleanup"),
        run_optional_cleanup(["pip3", "pip"], ["cache", "purge"], "pip cache cleanup"),
        run_optional_cleanup(["uv"], ["cache", "clean"], "uv cache cleanup"),
    ):
        if failure:
            failures.append(failure)

    for tmp_dir in INFRA_TMP_DIRS:
        log_tmp_usage(tmp_dir)
        failures.extend(cleanup_stale_infra_tmp_artifacts(tmp_dir=tmp_dir))
    for crash_dir in CRASH_REPORT_DIRS:
        failures.extend(cleanup_stale_crash_reports(crash_dir=crash_dir))
    trim_failure = cleanup_filesystem_free_space()
    if trim_failure:
        failures.append(trim_failure)
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
