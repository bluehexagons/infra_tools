from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
from typing import Optional

from lib.system_utils import get_current_username
from lib.validators import validate_username

BASE_PACKAGES = ["python3", "python3-venv", "curl", "git"]


def resolve_bootstrap_user(requested_user: Optional[str]) -> tuple[str, str]:
    """Resolve the local user whose shell environment should be configured."""
    if requested_user:
        username = requested_user
    elif os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        username = os.environ["SUDO_USER"]
    else:
        username = get_current_username()

    if not validate_username(username):
        raise ValueError(f"Invalid username: {username}")

    try:
        home_dir = pwd.getpwnam(username).pw_dir
    except KeyError as exc:
        raise ValueError(f"User not found: {username}") from exc

    return username, home_dir


def install_system_packages(shell: str) -> int:
    """Install local system packages needed to operate infra_tools."""
    if os.geteuid() != 0:
        print("Error: System package installation requires root privileges. Re-run with sudo or use --skip-system-packages.")
        return 1

    packages = list(BASE_PACKAGES)
    if shell == "bash":
        packages.append("bash-completion")

    print("Installing orchestration host packages...")
    update_result = subprocess.run(
        ["apt-get", "update", "-qq"],
        capture_output=True,
        text=True,
    )
    if update_result.returncode != 0:
        output = "\n".join(part for part in [update_result.stdout.strip(), update_result.stderr.strip()] if part)
        print(f"Error: failed to update package lists.{f' Output: {output}' if output else ''}")
        return 1

    install_result = subprocess.run(
        ["apt-get", "install", "-y", "-qq", *packages],
        capture_output=True,
        text=True,
    )
    if install_result.returncode != 0:
        output = "\n".join(part for part in [install_result.stdout.strip(), install_result.stderr.strip()] if part)
        print(f"Error: failed to install required packages.{f' Output: {output}' if output else ''}")
        return 1

    print(f"✓ Installed system packages: {', '.join(packages)}")
    return 0


def _resolve_self_command(script_path: str) -> list[str]:
    resolved_path = script_path
    if not os.path.isabs(resolved_path):
        resolved_path = shutil.which(resolved_path) or os.path.abspath(resolved_path)
    if resolved_path.endswith(".py"):
        return [sys.executable, resolved_path]
    return [resolved_path]


def run_orchestrator_bootstrap(
    script_path: str,
    shell: str,
    requested_user: Optional[str],
    skip_system_packages: bool = False,
) -> int:
    """Bootstrap a local orchestration host for infra_tools administration."""
    try:
        username, home_dir = resolve_bootstrap_user(requested_user)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Bootstrapping orchestration host for {username}...")

    if not skip_system_packages:
        result = install_system_packages(shell)
        if result != 0:
            return result

    command = _resolve_self_command(script_path) + ["python-tools", "--shell", shell]
    current_username = get_current_username()
    if username == current_username:
        return subprocess.run(command, check=False).returncode

    if os.geteuid() != 0:
        print("Error: Switching to another user requires root privileges.")
        return 1

    env = os.environ.copy()
    env["HOME"] = home_dir
    env["USER"] = username
    return subprocess.run(
        ["runuser", "-u", username, "--", *command],
        env=env,
        check=False,
    ).returncode
