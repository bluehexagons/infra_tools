#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(host: str, username: str) -> None:
    print(f"Server: {host}")
    print(f"Username: {username}")
    print()
    print(f"Connect via SSH: ssh {username}@{host}")
    print(f"View website: http://{host}")


def main() -> int:
    return setup_main(
        "server_web",
        "Remote Web Server Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
