#!/usr/bin/env python3

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.setup_common import setup_main
from lib.display import print_success_header


def success_message(config: SetupConfig) -> None:
    print_success_header(config)
    print()
    print(f"Connect via SSH: ssh {config.username}@{config.host}")


def main() -> int:
    return setup_main(
        "custom_steps",
        "Remote Custom Steps Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
