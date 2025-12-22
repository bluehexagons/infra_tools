#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(host: str, username: str, enable_rdp: bool = True, enable_x2go: bool = True) -> None:
    if enable_rdp:
        print(f"RDP: {host}:3389")
        print(f"  Client: Remmina, Microsoft Remote Desktop")
    if enable_x2go:
        print(f"X2Go: {host}:22 (SSH)")
        print(f"  Client: x2goclient, Session: XFCE")
    print(f"Username: {username}")
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
