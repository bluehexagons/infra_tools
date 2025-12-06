#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(ip: str, username: str) -> None:
    print(f"Server: {ip}")
    print(f"Username: {username}")
    print()
    print(f"Connect via SSH: ssh {username}@{ip}")


def main() -> int:
    return setup_main(
        "custom_steps",
        "Remote Custom Steps Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
