#!/usr/bin/env python3

from __future__ import annotations

import sys
from lib.config import SetupConfig
from lib.setup_common import setup_main
from lib.display import print_success_header, print_rdp_info


def success_message(config: SetupConfig) -> None:
    print_rdp_info(config)
    print_success_header(config)


def main() -> int:
    return setup_main(
        "workstation_desktop",
        "Remote Workstation Desktop Setup",
        success_message
    )


if __name__ == "__main__":
    sys.exit(main())
