#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main, print_success_header


def success_message(host: str, username: str, enable_rdp: bool = False, enable_x2go: bool = False,
                   friendly_name: str = None, tags: list = None) -> None:
    print(f"Proxmox Server: {host}")
    print(f"Username: {username}")
    if friendly_name or tags:
        from lib.setup_common import print_name_and_tags
        print()
        print_name_and_tags(friendly_name, tags)
    print()
    print(f"Connect via SSH: ssh root@{host}")
    print(f"Web UI: https://{host}:8006")


def main() -> int:
    return setup_main(
        "server_proxmox",
        "Proxmox Server Hardening",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
