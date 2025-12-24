#!/usr/bin/env python3

import sys
from lib.config import SetupConfig
from lib.setup_common import setup_main, print_name_and_tags


def success_message(config: SetupConfig) -> None:
    print(f"Proxmox Server: {config.host}")
    print(f"Username: {config.username}")
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)
    print()
    print(f"Connect via SSH: ssh root@{config.host}")
    print(f"Web UI: https://{config.host}:8006")


def main() -> int:
    return setup_main(
        "server_proxmox",
        "Proxmox Server Hardening",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
