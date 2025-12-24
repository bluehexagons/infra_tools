#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main, print_success_header, SetupConfig


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
