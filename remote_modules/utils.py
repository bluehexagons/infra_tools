"""Utility functions for remote setup."""

import os
import re
import secrets
import shlex
import string
import subprocess
import sys
from typing import Optional


def validate_username(username: str) -> bool:
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  Running: {cmd[:80]}..." if len(cmd) > 80 else f"  Running: {cmd}")
    sys.stdout.flush()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(f"    Warning: {result.stderr[:200]}")
            sys.stdout.flush()
    return result


def detect_os() -> str:
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
    except FileNotFoundError:
        print("Error: Cannot detect OS - /etc/os-release not found")
        sys.exit(1)

    if "ubuntu" in content or "debian" in content:
        return "debian"
    elif "fedora" in content:
        return "fedora"
    else:
        print("Error: Unsupported OS (only Debian/Ubuntu and Fedora are supported)")
        sys.exit(1)


def is_package_installed(package: str, os_type: str) -> bool:
    if os_type == "debian":
        result = subprocess.run(
            f"dpkg -l {shlex.quote(package)} 2>/dev/null | grep -q ^ii",
            shell=True, capture_output=True
        )
    else:
        result = subprocess.run(
            f"rpm -q {shlex.quote(package)} >/dev/null 2>&1",
            shell=True, capture_output=True
        )
    return result.returncode == 0


def is_service_active(service: str) -> bool:
    result = subprocess.run(
        f"systemctl is-active {shlex.quote(service)} >/dev/null 2>&1",
        shell=True, capture_output=True
    )
    return result.returncode == 0


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
