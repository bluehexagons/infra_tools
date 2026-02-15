"""Utility functions for remote setup."""

from __future__ import annotations

import secrets
import shlex
import string
import subprocess
import sys
from typing import Optional


_dry_run = False


def set_dry_run(enabled: bool) -> None:
    """Set dry-run mode globally."""
    global _dry_run
    _dry_run = enabled


def is_dry_run() -> bool:
    """Check if dry-run mode is enabled."""
    return _dry_run


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def run(cmd: str, check: bool = True, cwd: Optional[str] = None, capture_output: bool = False, text: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"  Running: {cmd[:80]}..." if len(cmd) > 80 else f"  Running: {cmd}")
    sys.stdout.flush()
    
    if is_dry_run():
        print("  [DRY-RUN] Command not executed")
        # CompletedProcess.args expects a sequence; provide a one-element list for consistency
        return subprocess.CompletedProcess(args=[cmd], returncode=0, stdout="", stderr="")
    
    result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=text, cwd=cwd)
    if check and result.returncode != 0:
        if getattr(result, 'stderr', None):
            print(f"    Warning: {result.stderr[:200]}")
            sys.stdout.flush()
    return result


def detect_os() -> None:
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
    except FileNotFoundError:
        print("Error: Cannot detect OS - /etc/os-release not found")
        sys.exit(1)

    if "debian" not in content:
        print("Error: Unsupported OS (only Debian is supported)")
        sys.exit(1)


def is_package_installed(package: str) -> bool:
    result = subprocess.run(
        f"dpkg -l {shlex.quote(package)} 2>/dev/null | grep -q ^ii",
        shell=True, capture_output=True
    )
    return result.returncode == 0


def is_service_active(service: str) -> bool:
    result = subprocess.run(
        f"systemctl is-active {shlex.quote(service)} >/dev/null 2>&1",
        shell=True, capture_output=True
    )
    return result.returncode == 0


def is_flatpak_app_installed(app_id: str) -> bool:
    """Return True if the given Flatpak application id is installed."""
    try:
        result = subprocess.run(
            f"flatpak info {shlex.quote(app_id)}",
            shell=True, capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

def user_exists(username: str) -> bool:
    result = subprocess.run(
        f"id {shlex.quote(username)}",
        shell=True, capture_output=True
    )
    return result.returncode == 0


def file_contains(filepath: str, content: str) -> bool:
    try:
        with open(filepath, 'r') as f:
            return content in f.read()
    except (FileNotFoundError, PermissionError):
        return False
