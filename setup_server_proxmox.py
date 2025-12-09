#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(host: str, username: str) -> None:
    print(f"Proxmox Server: {host}")
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
