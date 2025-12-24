#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main, print_success_header


def success_message(host: str, username: str, enable_rdp: bool = False, enable_x2go: bool = False,
                   friendly_name: str = None, tags: list = None) -> None:
    print_success_header(host, username, friendly_name, tags)
    print()
    print(f"Connect via SSH: ssh {username}@{host}")


def main() -> int:
    return setup_main(
        "custom_steps",
        "Remote Custom Steps Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
