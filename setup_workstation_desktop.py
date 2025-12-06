#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(ip: str, username: str) -> None:
    print(f"RDP: {ip}:3389")
    print(f"Username: {username}")
    print()
    print("Connect using RDP client (Remmina, Microsoft Remote Desktop)")


def main() -> int:
    return setup_main(
        "workstation_desktop",
        "Remote Workstation Desktop Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
