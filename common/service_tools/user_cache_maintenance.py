#!/usr/bin/env python3
"""Prune bounded developer-tool caches as the configured login user."""

from __future__ import annotations

import argparse
import os
import pwd
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from logging import INFO, WARNING

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

from lib.logging_utils import get_service_logger, log_event
from lib.maintenance_defaults import (
    CLEANUP_COMMAND_TIMEOUT_SECONDS,
    CODEX_CACHE_MAX_BYTES,
    GO_BUILD_CACHE_MAX_BYTES,
    GO_MODULE_CACHE_MAX_BYTES,
    NPM_CACHE_MAX_BYTES,
    OPENCODE_CACHE_MAX_BYTES,
    PIP_CACHE_MAX_BYTES,
    STALE_USER_TOOL_CACHE_MAX_AGE_DAYS,
    STALE_USER_TOOL_TMP_MAX_AGE_DAYS,
)
from lib.types import BYTES_PER_MB
from lib.validation import validate_filesystem_path


logger = get_service_logger("user_cache_maintenance", "common", use_syslog=True)
_TOOL_NOT_FOUND_EXIT = 77


@dataclass(frozen=True)
class UserContext:
    """Identity and home directory for the unprivileged maintenance process."""

    username: str
    home: str
    uid: int


@dataclass(frozen=True)
class CacheUsage:
    """Size and most recent modification time for a cache tree."""

    size_bytes: int
    newest_mtime: float | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse direct maintenance-script options."""
    parser = argparse.ArgumentParser(
        description="Audit and prune bounded caches owned by the current login user.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory caches and report cleanup actions without changing files",
    )
    return parser.parse_args(argv)


def resolve_user_context() -> UserContext:
    """Return the effective account and its validated home directory."""
    account = pwd.getpwuid(os.getuid())
    validate_filesystem_path(account.pw_dir, must_exist=True)
    return UserContext(account.pw_name, account.pw_dir, account.pw_uid)


def _tool_environment(context: UserContext) -> dict[str, str]:
    """Build an explicit home-scoped environment for optional tool commands."""
    environment = os.environ.copy()
    path_entries = (
        os.path.join(context.home, ".local", "bin"),
        os.path.join(context.home, ".opencode", "bin"),
        "/usr/local/go/bin",
        environment.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    )
    environment.update(
        {
            "HOME": context.home,
            "USER": context.username,
            "LOGNAME": context.username,
            "PATH": os.pathsep.join(path_entries),
        }
    )
    return environment


def run_tool_command(
    context: UserContext,
    command: list[str],
    *,
    load_nvm: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run an allowlisted tool command in the configured user's environment."""
    if not command:
        raise ValueError("Tool command must not be empty")

    path_prefix = os.pathsep.join(
        (
            os.path.join(context.home, ".local", "bin"),
            os.path.join(context.home, ".opencode", "bin"),
            "/usr/local/go/bin",
        )
    )
    shell_parts = [f"export PATH={shlex.quote(path_prefix)}:$PATH"]
    if load_nvm:
        nvm_dir = os.path.join(context.home, ".nvm")
        shell_parts.extend(
            (
                f"export NVM_DIR={shlex.quote(nvm_dir)}",
                '[ ! -s "$NVM_DIR/nvm.sh" ] || . "$NVM_DIR/nvm.sh"',
            )
        )
    shell_parts.extend(
        (
            f"command -v {shlex.quote(command[0])} >/dev/null || "
            f"exit {_TOOL_NOT_FOUND_EXIT}",
            f"exec {shlex.join(command)}",
        )
    )
    return subprocess.run(
        # Do not use a login shell here. Unattended maintenance must not depend
        # on, execute, or have its output polluted by interactive profile files.
        ["/bin/bash", "-c", "; ".join(shell_parts)],
        capture_output=True,
        text=True,
        cwd=context.home,
        env=_tool_environment(context),
        timeout=CLEANUP_COMMAND_TIMEOUT_SECONDS,
    )


def run_cleanup_command(
    context: UserContext,
    command: list[str],
    action: str,
    *,
    dry_run: bool,
    load_nvm: bool = False,
) -> str | None:
    """Run a supported cache command and return a concise failure summary."""
    if dry_run:
        log_event(
            logger,
            "Would run user cache cleanup command",
            action=action,
            command=shlex.join(command),
        )
        return None

    try:
        result = run_tool_command(context, command, load_nvm=load_nvm)
    except subprocess.TimeoutExpired:
        details = f"timed out after {CLEANUP_COMMAND_TIMEOUT_SECONDS}s"
        log_event(logger, f"{action} timed out", level=WARNING, error=details)
        return f"{action}: {details}"
    except OSError as exc:
        details = str(exc)
        log_event(logger, f"{action} could not run", level=WARNING, error=details)
        return f"{action}: {details}"

    if result.returncode == _TOOL_NOT_FOUND_EXIT:
        log_event(logger, f"{action} not available, skipping")
        return None
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        log_event(logger, f"{action} failed", level=WARNING, error=details)
        return f"{action}: {details}"

    log_event(logger, f"{action} completed", level=INFO)
    return None


def query_cache_path(
    context: UserContext,
    commands: tuple[list[str], ...],
    action: str,
    *,
    load_nvm: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """Return a tool-reported cache path, selected executable, and failure."""
    for command in commands:
        try:
            result = run_tool_command(context, command, load_nvm=load_nvm)
        except (OSError, subprocess.SubprocessError) as exc:
            details = str(exc)
            log_event(logger, f"{action} could not run", level=WARNING, error=details)
            return None, None, f"{action}: {details}"

        if result.returncode == _TOOL_NOT_FOUND_EXIT:
            continue
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            log_event(logger, f"{action} failed", level=WARNING, error=details)
            return None, None, f"{action}: {details}"

        output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not output_lines:
            details = "tool returned an empty cache path"
            log_event(logger, f"{action} failed", level=WARNING, error=details)
            return None, None, f"{action}: {details}"
        return output_lines[-1], command[0], None

    log_event(logger, f"{action} not available, skipping")
    return None, None, None


def is_safe_managed_path(context: UserContext, path: str, label: str) -> bool:
    """Return whether a cache path is absolute, home-contained, and not a link."""
    try:
        validate_filesystem_path(path, must_exist=False)
        if not os.path.isabs(path):
            raise ValueError("path is not absolute")
        resolved_home = os.path.realpath(context.home)
        resolved_path = os.path.realpath(path)
        if resolved_path == resolved_home:
            raise ValueError("path resolves to the user home")
        if os.path.commonpath((resolved_home, resolved_path)) != resolved_home:
            raise ValueError("path resolves outside the user home")
        if os.path.islink(path):
            raise ValueError("path is a symbolic link")
    except (OSError, ValueError) as exc:
        log_event(
            logger,
            "Skipping unsafe user cache path",
            level=WARNING,
            cache=label,
            path=path,
            error=str(exc),
        )
        return False
    return True


def cache_usage(path: str) -> CacheUsage:
    """Measure a cache tree without following symbolic links."""
    if not os.path.exists(path):
        return CacheUsage(0, None)

    size_bytes = 0
    newest_mtime: float | None = None
    pending_paths = [path]
    while pending_paths:
        current_path = pending_paths.pop()
        stat_result = os.lstat(current_path)
        if os.path.islink(current_path):
            continue
        if newest_mtime is None or stat_result.st_mtime > newest_mtime:
            newest_mtime = stat_result.st_mtime
        if not os.path.isdir(current_path):
            size_bytes += stat_result.st_size
            continue

        with os.scandir(current_path) as entries:
            pending_paths.extend(entry.path for entry in entries)

    return CacheUsage(size_bytes, newest_mtime)


def inventory_cache(
    context: UserContext,
    label: str,
    path: str,
) -> tuple[CacheUsage | None, str | None]:
    """Validate, measure, and log one user-owned cache."""
    if not is_safe_managed_path(context, path, label):
        return None, None
    try:
        usage = cache_usage(path)
    except OSError as exc:
        details = str(exc)
        log_event(
            logger,
            "Could not inspect user cache",
            level=WARNING,
            cache=label,
            path=path,
            error=details,
        )
        return None, f"{label} inventory: {details}"

    age_days = None
    if usage.newest_mtime is not None:
        age_days = max(0, int((time.time() - usage.newest_mtime) / (24 * 60 * 60)))
    log_event(
        logger,
        "User cache inventory",
        cache=label,
        path=path,
        size_mb=round(usage.size_bytes / BYTES_PER_MB, 1),
        newest_age_days=age_days,
    )
    return usage, None


def tool_is_active(process_names: tuple[str, ...], proc_root: str = "/proc") -> bool:
    """Detect matching current-user executables without reading command lines."""
    current_uid = os.getuid()
    try:
        process_entries = os.scandir(proc_root)
    except OSError:
        return True

    with process_entries:
        for entry in process_entries:
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat(follow_symlinks=False).st_uid != current_uid:
                    continue
                with open(os.path.join(entry.path, "comm"), encoding="utf-8") as handle:
                    process_name = handle.read().strip().lower()
            except OSError:
                continue
            if any(
                process_name == name or process_name.startswith(f"{name}-")
                for name in process_names
            ):
                return True
    return False


def cleanup_managed_directory(
    context: UserContext,
    *,
    label: str,
    path: str,
    max_bytes: int,
    max_age_days: int,
    process_names: tuple[str, ...],
    dry_run: bool,
) -> list[str]:
    """Remove a rebuildable cache when stale or oversized and its tool is idle."""
    usage, failure = inventory_cache(context, label, path)
    if failure:
        return [failure]
    if usage is None or usage.newest_mtime is None:
        return []

    reasons: list[str] = []
    if usage.size_bytes > max_bytes:
        reasons.append("size limit exceeded")
    cutoff = time.time() - (max_age_days * 24 * 60 * 60)
    if usage.newest_mtime < cutoff:
        reasons.append("stale")
    if not reasons:
        return []
    if tool_is_active(process_names):
        log_event(
            logger,
            "User cache cleanup deferred while tool is active",
            cache=label,
            path=path,
            reason=", ".join(reasons),
        )
        return []

    if dry_run:
        log_event(
            logger,
            "Would remove rebuildable user cache",
            cache=label,
            path=path,
            reason=", ".join(reasons),
        )
        return []

    try:
        if not os.path.isdir(path):
            raise OSError("managed cache path is not a directory")
        shutil.rmtree(path)
    except OSError as exc:
        details = str(exc)
        log_event(
            logger,
            "Failed to remove rebuildable user cache",
            level=WARNING,
            cache=label,
            path=path,
            error=details,
        )
        return [f"{label} cleanup: {details}"]

    log_event(
        logger,
        "Removed rebuildable user cache",
        cache=label,
        path=path,
        reason=", ".join(reasons),
    )
    return []


def cleanup_stale_children(
    context: UserContext,
    *,
    label: str,
    path: str,
    max_age_days: int,
    process_names: tuple[str, ...],
    dry_run: bool,
) -> list[str]:
    """Remove old non-link entries from an allowlisted tool temp directory."""
    if not is_safe_managed_path(context, path, label) or not os.path.exists(path):
        return []
    if tool_is_active(process_names):
        log_event(
            logger,
            "User temp cleanup deferred while tool is active",
            cache=label,
            path=path,
        )
        return []

    cutoff = time.time() - (max_age_days * 24 * 60 * 60)
    failures: list[str] = []
    removed_count = 0
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        return [f"{label} inventory: {exc}"]

    for entry in entries:
        if entry.is_symlink():
            continue
        try:
            usage = cache_usage(entry.path)
            if usage.newest_mtime is None or usage.newest_mtime >= cutoff:
                continue
            if dry_run:
                log_event(
                    logger,
                    "Would remove stale user tool temp entry",
                    cache=label,
                    path=entry.path,
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
            removed_count += 1
        except OSError as exc:
            details = str(exc)
            log_event(
                logger,
                "Failed to remove stale user tool temp entry",
                level=WARNING,
                cache=label,
                path=entry.path,
                error=details,
            )
            failures.append(f"{entry.path}: {details}")

    if removed_count:
        log_event(
            logger,
            "Removed stale user tool temp entries",
            cache=label,
            path=path,
            removed_count=removed_count,
        )
    return failures


def cleanup_npm_cache(context: UserContext, *, dry_run: bool) -> list[str]:
    """Garbage-collect npm cache data and enforce a high-water size limit."""
    path, executable, failure = query_cache_path(
        context,
        (["npm", "config", "get", "cache"],),
        "npm cache path query",
        load_nvm=True,
    )
    if failure:
        return [failure]
    if path is None or executable is None:
        return []

    usage, inventory_failure = inventory_cache(context, "npm", path)
    failures = [inventory_failure] if inventory_failure else []
    if usage is None:
        return failures
    verify_failure = run_cleanup_command(
        context,
        [executable, "cache", "verify"],
        "npm cache verification and garbage collection",
        dry_run=dry_run,
        load_nvm=True,
    )
    if verify_failure:
        failures.append(verify_failure)
    elif not dry_run:
        usage, post_verify_failure = inventory_cache(context, "npm", path)
        if post_verify_failure:
            failures.append(post_verify_failure)
    if (
        verify_failure is None
        and usage is not None
        and usage.size_bytes > NPM_CACHE_MAX_BYTES
    ):
        clean_failure = run_cleanup_command(
            context,
            [executable, "cache", "clean", "--force"],
            "npm oversized cache cleanup",
            dry_run=dry_run,
            load_nvm=True,
        )
        if clean_failure:
            failures.append(clean_failure)
    return failures


def cleanup_pip_cache(context: UserContext, *, dry_run: bool) -> list[str]:
    """Purge pip's cache only after it exceeds its configured size limit."""
    path, executable, failure = query_cache_path(
        context,
        (["pip3", "cache", "dir"], ["pip", "cache", "dir"]),
        "pip cache path query",
    )
    if failure:
        return [failure]
    if path is None or executable is None:
        return []

    usage, inventory_failure = inventory_cache(context, "pip", path)
    failures = [inventory_failure] if inventory_failure else []
    if usage is not None and usage.size_bytes > PIP_CACHE_MAX_BYTES:
        cleanup_failure = run_cleanup_command(
            context,
            [executable, "cache", "purge"],
            "pip oversized cache cleanup",
            dry_run=dry_run,
        )
        if cleanup_failure:
            failures.append(cleanup_failure)
    return failures


def cleanup_uv_cache(context: UserContext, *, dry_run: bool) -> list[str]:
    """Use uv's supported periodic pruning operation."""
    path, executable, failure = query_cache_path(
        context,
        (["uv", "cache", "dir"],),
        "uv cache path query",
    )
    if failure:
        return [failure]
    if path is None or executable is None:
        return []

    usage, inventory_failure = inventory_cache(context, "uv", path)
    failures = [inventory_failure] if inventory_failure else []
    if usage is None:
        return failures
    cleanup_failure = run_cleanup_command(
        context,
        [executable, "cache", "prune"],
        "uv cache prune",
        dry_run=dry_run,
    )
    if cleanup_failure:
        failures.append(cleanup_failure)
    return failures


def cleanup_go_cache(
    context: UserContext,
    *,
    cache_name: str,
    go_env_name: str,
    max_bytes: int,
    clean_args: list[str],
    dry_run: bool,
) -> list[str]:
    """Clean one Go cache through the go command after it exceeds its limit."""
    path, executable, failure = query_cache_path(
        context,
        (["go", "env", go_env_name],),
        f"{cache_name} path query",
    )
    if failure:
        return [failure]
    if path is None or executable is None:
        return []

    usage, inventory_failure = inventory_cache(context, cache_name, path)
    failures = [inventory_failure] if inventory_failure else []
    if usage is not None and usage.size_bytes > max_bytes:
        cleanup_failure = run_cleanup_command(
            context,
            [executable, "clean"] + clean_args,
            f"{cache_name} oversized cleanup",
            dry_run=dry_run,
        )
        if cleanup_failure:
            failures.append(cleanup_failure)
    return failures


def cleanup_agent_caches(context: UserContext, *, dry_run: bool) -> list[str]:
    """Clean only explicitly rebuildable Codex and OpenCode paths."""
    xdg_cache_home = os.environ.get(
        "XDG_CACHE_HOME",
        os.path.join(context.home, ".cache"),
    )
    codex_home = os.environ.get("CODEX_HOME", os.path.join(context.home, ".codex"))
    failures = cleanup_managed_directory(
        context,
        label="OpenCode",
        path=os.path.join(xdg_cache_home, "opencode"),
        max_bytes=OPENCODE_CACHE_MAX_BYTES,
        max_age_days=STALE_USER_TOOL_CACHE_MAX_AGE_DAYS,
        process_names=("opencode", "opencode-cli"),
        dry_run=dry_run,
    )
    failures.extend(
        cleanup_managed_directory(
            context,
            label="Codex",
            path=os.path.join(codex_home, "cache"),
            max_bytes=CODEX_CACHE_MAX_BYTES,
            max_age_days=STALE_USER_TOOL_CACHE_MAX_AGE_DAYS,
            process_names=("codex",),
            dry_run=dry_run,
        )
    )
    failures.extend(
        cleanup_stale_children(
            context,
            label="Codex temporary files",
            path=os.path.join(codex_home, "tmp"),
            max_age_days=STALE_USER_TOOL_TMP_MAX_AGE_DAYS,
            process_names=("codex",),
            dry_run=dry_run,
        )
    )
    return failures


def run_user_cache_maintenance(context: UserContext, *, dry_run: bool) -> list[str]:
    """Run each independent user cache policy and collect failures."""
    failures = cleanup_npm_cache(context, dry_run=dry_run)
    failures.extend(cleanup_pip_cache(context, dry_run=dry_run))
    failures.extend(cleanup_uv_cache(context, dry_run=dry_run))
    failures.extend(
        cleanup_go_cache(
            context,
            cache_name="Go build cache",
            go_env_name="GOCACHE",
            max_bytes=GO_BUILD_CACHE_MAX_BYTES,
            clean_args=["-cache", "-testcache", "-fuzzcache"],
            dry_run=dry_run,
        )
    )
    failures.extend(
        cleanup_go_cache(
            context,
            cache_name="Go module cache",
            go_env_name="GOMODCACHE",
            max_bytes=GO_MODULE_CACHE_MAX_BYTES,
            clean_args=["-modcache"],
            dry_run=dry_run,
        )
    )
    failures.extend(cleanup_agent_caches(context, dry_run=dry_run))
    return failures


def main(argv: list[str] | None = None) -> int:
    """Run bounded user cache maintenance."""
    args = parse_args(argv)
    try:
        context = resolve_user_context()
    except (KeyError, ValueError) as exc:
        log_event(
            logger,
            "Could not resolve cache-maintenance user",
            level=WARNING,
            error=str(exc),
        )
        return 1

    if context.uid == 0:
        log_event(logger, "Skipping user cache maintenance for the root account")
        return 0

    log_event(
        logger,
        "Starting user cache maintenance",
        username=context.username,
        dry_run=args.dry_run,
    )
    failures = run_user_cache_maintenance(context, dry_run=args.dry_run)
    if failures:
        log_event(
            logger,
            "User cache maintenance failed",
            level=WARNING,
            failure_count=len(failures),
            details="\n".join(failures),
        )
        return 1

    log_event(
        logger,
        "User cache maintenance completed successfully",
        username=context.username,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
