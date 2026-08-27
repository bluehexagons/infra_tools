"""Redacted local support snapshots for infra-tools agent VMs."""

from __future__ import annotations

import argparse
import json
import os
import platform
import pwd
import stat
from datetime import datetime, timezone
from typing import Optional

from lib.atomic_io import write_json_atomic
from lib.types import JSONDict
from lib.validation import validate_filesystem_path


def _effective_home() -> str:
    try:
        return pwd.getpwuid(os.geteuid()).pw_dir
    except KeyError as exc:
        raise RuntimeError("Could not resolve the current agent user's home") from exc


def _expand_home_path(path: str, home: str) -> str:
    if path == "~":
        return home
    if path.startswith(f"~{os.path.sep}"):
        return os.path.join(home, path[2:])
    return path


def _t3_log_summary(home: str) -> JSONDict:
    root = os.path.join(home, ".t3", "userdata", "logs")
    summary = {
        "available": False,
        "current_files": 0,
        "rotated_files": 0,
        "total_bytes": 0,
        "newest_mtime": None,
    }
    if os.path.islink(root) or not os.path.isdir(root):
        return summary
    newest: float | None = None
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not os.path.islink(os.path.join(current, name))
        ]
        for filename in filenames:
            path = os.path.join(current, filename)
            try:
                details = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(details.st_mode):
                continue
            summary["total_bytes"] = int(summary["total_bytes"]) + details.st_size
            if filename.rsplit(".", 1)[-1].isdigit():
                summary["rotated_files"] = int(summary["rotated_files"]) + 1
            else:
                summary["current_files"] = int(summary["current_files"]) + 1
            newest = details.st_mtime if newest is None else max(newest, details.st_mtime)
    summary["available"] = True
    summary["newest_mtime"] = (
        datetime.fromtimestamp(newest, timezone.utc).isoformat().replace("+00:00", "Z")
        if newest is not None
        else None
    )
    return summary


def build_agent_support_bundle(
    home: Optional[str] = None,
    *,
    browser_smoke: bool = False,
) -> JSONDict:
    """Compose diagnostic results while omitting paths, identities, and log text."""
    from lib.agent_cli import (
        DEFAULT_DOCTOR_TOOLS,
        inspect_agent_tools,
        inspect_browser_automation,
        inspect_host_readiness,
        inspect_t3code,
    )

    user_home = os.path.abspath(home or _effective_home())
    tools = inspect_agent_tools(list(DEFAULT_DOCTOR_TOOLS), home=user_home)
    host = inspect_host_readiness(user_home)
    t3code = inspect_t3code(user_home)
    browser = inspect_browser_automation(user_home, run_smoke=browser_smoke)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system": {
            "platform": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "tools": [
            {
                key: record.get(key)
                for key in (
                    "tool",
                    "installed",
                    "version",
                    "credential",
                    "credential_healthy",
                    "credential_status",
                )
                if key in record
            }
            for record in tools
        ],
        "host": {
            "healthy": host["healthy"],
            "status": host["status"],
            "memory": host["memory"],
            "disk": {
                key: value
                for key, value in host["disk"].items()
                if key != "path"
            },
            "agent_storage": {
                "size_bytes": host["agent_storage"]["size_bytes"],
                "codex_release_count": host["agent_storage"]["codex_release_count"],
            },
            "t3_service": host["t3_service"],
            "maintenance": host["maintenance"],
            "maintenance_hold": host["maintenance_hold"],
            "reboot_pending": host["reboot_pending"],
            "warnings": host["warnings"],
            "errors": host["errors"],
        },
        "t3code": {
            "healthy": t3code["healthy"],
            "checks": t3code["checks"],
            "version": t3code["version"],
        },
        "browser": {
            "installed": browser["installed"],
            "registrations": browser["registrations"],
            "configured": browser["configured"],
            "smoke_test": browser["smoke_test"],
            "healthy": browser["healthy"],
        },
        "t3_logs": _t3_log_summary(user_home),
        "privacy": {
            "log_contents_included": False,
            "repository_contents_included": False,
            "credential_contents_included": False,
            "user_identity_included": False,
        },
    }


def write_agent_support_bundle(bundle: JSONDict, output: str, home: str) -> str:
    """Write a new private support snapshot below the current user's home."""
    user_home = os.path.realpath(os.path.abspath(home))
    path = os.path.abspath(_expand_home_path(output, user_home))
    validate_filesystem_path(path, must_exist=False)
    try:
        contained = os.path.commonpath((os.path.realpath(path), user_home)) == user_home
    except ValueError:
        contained = False
    if not contained or path == user_home:
        raise ValueError("Support bundle output must remain below the current user's home")
    current = user_home
    for component in os.path.relpath(path, user_home).split(os.path.sep)[:-1]:
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"Support bundle path contains a symbolic link: {current}")
    parent = os.path.dirname(path)
    if os.path.islink(parent) or not os.path.isdir(parent):
        raise ValueError(f"Support bundle parent must be an existing directory: {parent}")
    if os.path.lexists(path):
        raise ValueError(f"Support bundle output already exists: {path}")
    write_json_atomic(path, bundle, mode=0o600, sort_keys=True)
    return path


def run_agent_support_command(args: argparse.Namespace) -> int:
    """Build and optionally save a redacted local support snapshot."""
    try:
        home = os.path.abspath(_effective_home())
        bundle = build_agent_support_bundle(
            home,
            browser_smoke=args.browser_smoke,
        )
        if args.output:
            path = write_agent_support_bundle(bundle, args.output, home)
            print(path)
        else:
            print(json.dumps(bundle, indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0
