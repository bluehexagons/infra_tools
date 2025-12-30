#!/usr/bin/env python3

import sys
from lib.config import SetupConfig
from lib.setup_common import setup_main
from lib.display import print_success_header


def success_message(config: SetupConfig) -> None:
    print_success_header(config)
    print()
    print(f"Connect via SSH: ssh {config.username}@{config.host}")


def main() -> int:
    return setup_main(
        "server_dev",
        "Remote Server Development Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
