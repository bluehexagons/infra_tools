#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main


def success_message(ip: str, username: str) -> None:
    print(f"Proxmox Server: {ip}")
    print()
    print(f"Connect via SSH: ssh root@{ip}")
    print(f"Web UI: https://{ip}:8006")


def main() -> int:
    return setup_main(
        "server_proxmox",
        "Proxmox Server Hardening",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
