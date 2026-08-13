"""Utility functions for remote setup."""

from __future__ import annotations

import os
import pwd
import re
import secrets
import shlex
import string
import subprocess
import sys
from typing import Callable, Optional

from lib.validation import validate_package_name


_dry_run = False


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<key>\b[A-Za-z_][A-Za-z0-9_-]*)(?P<separator>\s*=\s*)"
    r"(?P<value>[^\s;&|]+)"
)
_SECRET_OPTION_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(--?(?:password|passwd|secret|token|api[-_]?key|private[-_]?key|"
    r"credentials?)(?:=|\s+))([^\s;&|]+)"
)
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "api-key",
    "private_key",
    "private-key",
    "credential",
)


def _redact_command(value: str) -> str:
    """Redact common secret assignments and command-line option values."""
    def replace_assignment(match: re.Match[str]) -> str:
        key = match.group("key")
        if not any(marker in key.lower() for marker in _SECRET_KEY_MARKERS):
            return match.group(0)
        return f"{key}{match.group('separator')}<redacted>"

    redacted = _SECRET_ASSIGNMENT_RE.sub(replace_assignment, value)
    return _SECRET_OPTION_RE.sub(r"\1<redacted>", redacted)


class CommandExecutionError(RuntimeError):
    """Raised when a required command exits unsuccessfully."""

    def __init__(
        self,
        command: str,
        returncode: int,
        stderr: Optional[str] = None,
        *,
        result: Optional[subprocess.CompletedProcess[str]] = None,
    ) -> None:
        self.command = _redact_command(command)
        self.returncode = returncode
        self.stderr = _redact_command(stderr) if stderr else stderr
        self.result = result
        message = f"Command failed with exit code {returncode}: {self.command}"
        if self.stderr:
            message += f"\n{self.stderr[:500]}"
        super().__init__(message)


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


def run(
    cmd: str,
    check: bool = True,
    cwd: Optional[str] = None,
    capture_output: bool = False,
    text: bool = True,
    display_cmd: Optional[str] = None,
    input_data: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    log_cmd = _redact_command(display_cmd if display_cmd is not None else cmd)
    print(f"  Running: {log_cmd[:80]}..." if len(log_cmd) > 80 else f"  Running: {log_cmd}")
    sys.stdout.flush()
    
    if is_dry_run():
        print("  [DRY-RUN] Command not executed")
        # CompletedProcess.args expects a sequence; provide a one-element list for consistency
        return subprocess.CompletedProcess(args=[cmd], returncode=0, stdout="", stderr="")

    command = ["/bin/bash", "-lc", cmd] if _requires_shell(cmd) else shlex.split(cmd)
    run_kwargs = {
        "capture_output": capture_output,
        "text": text,
        "cwd": cwd,
    }
    if input_data is not None:
        run_kwargs["input"] = input_data
    result = subprocess.run(command, **run_kwargs)
    if check and result.returncode != 0:
        if getattr(result, 'stderr', None):
            warning = _redact_command(result.stderr) if isinstance(result.stderr, str) else result.stderr
            print(f"    Warning: {warning[:200]}")
            sys.stdout.flush()
        raise CommandExecutionError(
            log_cmd,
            result.returncode,
            result.stderr if isinstance(result.stderr, str) else None,
            result=result,
        )
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


SUPPORTED_OS_IDS = {"debian", "ubuntu", "linuxmint"}


def read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    """Read the small KEY=VALUE format used by Linux ``os-release`` files."""
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as file_obj:
        for line in file_obj:
            key, separator, value = line.partition("=")
            if not separator or not key or key.strip() != key:
                continue
            values[key] = value.strip().strip('"').strip("'")
    return values


def get_os_id(path: str = "/etc/os-release") -> str:
    """Return a normalized distribution ID, or an empty string if unknown."""

    try:
        release = read_os_release(path)
    except OSError:
        return ""
    return release.get("ID", "").lower()


def confirm_unsupported_environment(
    operation: str,
    *,
    input_fn: Optional[Callable[[str], str]] = None,
) -> bool:
    """Ask before a local operation runs on an unsupported distribution."""

    distro_id = get_os_id()
    if distro_id in SUPPORTED_OS_IDS:
        return True

    display_id = distro_id or "unknown"
    print(
        f"Warning: {operation} is running on unsupported host distribution "
        f"'{display_id}'."
    )
    print(
        "Debian is officially supported; Ubuntu and Linux Mint are "
        "best-effort. Other distributions may lack compatible package tools."
    )
    prompt = f"Continue with {operation} anyway? [y/N] "
    try:
        response = (input_fn or input)(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False

    if response.strip().lower() in {"y", "yes"}:
        return True

    print("Cancelled.")
    return False


def detect_os() -> str:
    try:
        release = read_os_release()
    except FileNotFoundError:
        print("Error: Cannot detect OS - /etc/os-release not found")
        sys.exit(1)

    distro_id = release.get("ID", "").lower()
    if distro_id not in SUPPORTED_OS_IDS:
        print(
            "Error: Unsupported OS (Debian is officially supported; "
            "Ubuntu and Linux Mint are best-effort)"
        )
        sys.exit(1)

    return {
        "debian": "Debian",
        "ubuntu": "Ubuntu (Debian-compatible)",
        "linuxmint": "Linux Mint (Ubuntu/Debian-compatible)",
    }[distro_id]


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
) -> bool:
    """Run install command and verify using provided verification function.
    
    Args:
        name: Display name for messages
        install_cmd: Command to run
        verify_fn: Callable that returns True if installed

    Returns:
        True if verification passed
    """
    if verify_fn():
        print(f"  ✓ {name} already installed")
        return True

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    print(f"  Installing {name}...")
    run(install_cmd, check=False)
    
    if verify_fn():
        print(f"  ✓ {name} installed")
        return True
    
    print(f"  ⚠ Failed to install {name}")
    return False


def install_package(name: str, package: str, install_cmd: str) -> bool:
    """Install an apt package and verify success.
    
    Args:
        name: Display name for messages
        package: Package name to check (for verification)
        install_cmd: Command to run for installation

    Returns:
        True if installed, False otherwise
    """
    return install_with_verify(
        name,
        install_cmd,
        lambda pkg=package: is_package_installed(pkg),
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


def get_user_home(username: str) -> str:
    """Return the home directory recorded for an existing Unix account."""
    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {username}") from exc


def file_contains(filepath: str, content: str) -> bool:
    try:
        with open(filepath, 'r') as f:
            return content in f.read()
    except (FileNotFoundError, PermissionError):
        return False
