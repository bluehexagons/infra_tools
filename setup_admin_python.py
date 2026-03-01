#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys

from common.common_steps import configure_auto_update_uv, install_python
from lib.config import SetupConfig
from lib.system_utils import get_current_username
from lib.validators import validate_username


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Python tooling (python aliases, uv, and shell completions) on the local system."
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("SUDO_USER") or get_current_username(),
        help="Target user for uv installation and updates (default: SUDO_USER/current user)",
    )
    return parser.parse_args()


def main() -> int:
    if os.geteuid() != 0:
        print("Error: This script must be run as root (use sudo).")
        return 1

    args = parse_args()
    if not validate_username(args.username):
        print(f"Error: Invalid username: {args.username}")
        return 1

    config = SetupConfig(
        host="localhost",
        username=args.username,
        system_type="custom_steps",
        install_python=True,
    )

    install_python(config)
    configure_auto_update_uv(config)
    print("✓ Python tooling setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
