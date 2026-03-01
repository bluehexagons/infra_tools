#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from common.common_steps import install_or_update_uv
from lib.system_utils import get_current_username
from lib.validators import validate_username


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install local Python tooling for infra_tools (current user, no root required)."
    )
    parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh"],
        default="bash",
        help="Shell to configure for completion (default: bash)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    username = get_current_username()
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1

    python3_path = shutil.which("python3")
    if not python3_path:
        print("Error: python3 is required but not found on PATH.")
        return 1

    user_home = os.path.expanduser("~")
    local_bin = os.path.join(user_home, ".local", "bin")
    os.makedirs(local_bin, exist_ok=True)

    python_alias = os.path.join(local_bin, "python")
    if shutil.which("python") is None and not os.path.exists(python_alias):
        os.symlink(python3_path, python_alias)
        print(f"✓ Added local python alias: {python_alias} -> {python3_path}")
    else:
        print("✓ python command already available")

    if not install_or_update_uv(user_home=user_home, username=None):
        print("Error: failed to install/update uv.")
        return 1

    uv_path = os.path.join(local_bin, "uv")
    safe_uv = shlex.quote(uv_path)
    argcomplete_result = subprocess.run(
        f"{safe_uv} tool install --upgrade argcomplete",
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True
    )
    if argcomplete_result.returncode != 0:
        print(f"Error: failed to install argcomplete with uv: {argcomplete_result.stderr.strip()}")
        return 1
    print("✓ argcomplete installed via uv")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    completions_script = os.path.join(script_dir, "setup_completions.py")
    if not os.path.exists(completions_script):
        print(f"Error: setup_completions.py not found: {completions_script}")
        return 1

    completion_result = subprocess.run(
        [sys.executable, completions_script, "--user", "--shell", args.shell],
        capture_output=True,
        text=True
    )
    if completion_result.returncode != 0:
        print(completion_result.stdout, end="")
        if completion_result.stderr:
            print(completion_result.stderr, end="")
        return 1

    print(completion_result.stdout, end="")
    print("✓ Local infra_tools Python install complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
