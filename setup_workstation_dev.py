#!/usr/bin/env python3

from __future__ import annotations

import sys
from lib.config import SetupConfig
from lib.setup_common import setup_main
from lib.display import print_success_header, print_rdp_x2go_info


def success_message(config: SetupConfig) -> None:
    print_rdp_x2go_info(config)
    print_success_header(config)


def main() -> int:
    return setup_main(
        "workstation_dev",
        "Remote Workstation Dev Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
