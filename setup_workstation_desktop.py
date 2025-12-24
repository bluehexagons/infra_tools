#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main, print_success_header, print_rdp_x2go_info, SetupConfig


def success_message(config: SetupConfig) -> None:
    print_rdp_x2go_info(config)
    print_success_header(config)


def main() -> int:
    return setup_main(
        "workstation_desktop",
        "Remote Workstation Desktop Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
