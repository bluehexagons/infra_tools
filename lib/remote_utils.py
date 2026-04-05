"""Utility functions for remote setup."""

from __future__ import annotations

import secrets
import shlex
import string
import subprocess
import sys
from typing import Optional, Callable

from lib.validation import validate_package_name


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


def run(cmd: str, check: bool = True, cwd: Optional[str] = None, capture_output: bool = False, text: bool = True, display_cmd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    log_cmd = display_cmd if display_cmd is not None else cmd
    print(f"  Running: {log_cmd[:80]}..." if len(log_cmd) > 80 else f"  Running: {log_cmd}")
    sys.stdout.flush()
    
    if is_dry_run():
        print("  [DRY-RUN] Command not executed")
        # CompletedProcess.args expects a sequence; provide a one-element list for consistency
        return subprocess.CompletedProcess(args=[cmd], returncode=0, stdout="", stderr="")

    if _requires_shell(cmd):
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=capture_output,
            text=text,
            cwd=cwd,
        )
    else:
        result = subprocess.run(shlex.split(cmd), capture_output=capture_output, text=text, cwd=cwd)
    if check and result.returncode != 0:
        if getattr(result, 'stderr', None):
            print(f"    Warning: {result.stderr[:200]}")
            sys.stdout.flush()
    return result


def _requires_shell(cmd: str) -> bool:
    """Return True when a command string depends on shell parsing."""

    stripped = cmd.strip()
    if not stripped:
        return False

    if stripped.startswith(("export ", ".", "source ")):
        return True

    first_token = stripped.split(None, 1)[0]
    if "=" in first_token and not first_token.startswith(("/", "./")):
        return True

    shell_metacharacters = ("|", "&&", "||", ";", ">", "<", "$", "`", "$(", "\n")
    return any(token in stripped for token in shell_metacharacters)


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
    safe_package = validate_package_name(package)
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", safe_package],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "install ok installed" in result.stdout


def install_with_verify(
    name: str,
    install_cmd: str,
    verify_fn: Callable[[], bool],
    required: bool = True
) -> bool:
    """Run install command and verify using provided verification function.
    
    Args:
        name: Display name for messages
        install_cmd: Command to run
        verify_fn: Callable that returns True if installed
        required: Unused; kept for API compatibility
    
    Returns:
        True if verification passed
    """
    if verify_fn():
        print(f"  ✓ {name} already installed")
        return True
    
    print(f"  Installing {name}...")
    run(install_cmd, check=False)
    
    if verify_fn():
        print(f"  ✓ {name} installed")
        return True
    
    print(f"  ⚠ Failed to install {name}")
    return False


def install_package(name: str, package: str, install_cmd: str, required: bool = True) -> bool:
    """Install an apt package and verify success.
    
    Args:
        name: Display name for messages
        package: Package name to check (for verification)
        install_cmd: Command to run for installation
        required: Unused; kept for API compatibility
    
    Returns:
        True if installed, False otherwise
    """
    return install_with_verify(
        name,
        install_cmd,
        lambda pkg=package: is_package_installed(pkg),
        required
    )


def is_service_active(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True,
    )
    return result.returncode == 0


def user_exists(username: str) -> bool:
    result = subprocess.run(
        ["id", username],
        capture_output=True,
    )
    return result.returncode == 0


def file_contains(filepath: str, content: str) -> bool:
    try:
        with open(filepath, 'r') as f:
            return content in f.read()
    except (FileNotFoundError, PermissionError):
        return False
