#!/usr/bin/env python3

import sys
from lib.setup_common import setup_main, print_success_header, print_rdp_x2go_info


def success_message(host: str, username: str, enable_rdp: bool = True, enable_x2go: bool = True,
                   friendly_name: str = None, tags: list = None) -> None:
    print_rdp_x2go_info(host, enable_rdp, enable_x2go)
    print_success_header(host, username, friendly_name, tags)


def main() -> int:
    return setup_main(
        "workstation_desktop",
        "Remote Workstation Desktop Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
