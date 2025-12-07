#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(ip: str, username: str) -> None:
    print(f"RDP: {ip}:3389")
    print(f"Username: {username}")
    print()
    print("Connect using RDP client (Remmina, Microsoft Remote Desktop)")
    print()
    print("PC Dev setup includes:")
    print("  - Desktop environment with RDP access")
    print("  - Remmina RDP client for remote connections")
    print("  - LibreOffice (installed by default)")
    print("  - Standard desktop applications")


def main() -> int:
    return setup_main(
        "pc_dev",
        "PC Development Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
