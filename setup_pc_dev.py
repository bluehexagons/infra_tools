#!/usr/bin/env python3

import sys
from lib.config import SetupConfig
from lib.setup_common import setup_main
from lib.display import print_success_header, print_rdp_x2go_info


def success_message(config: SetupConfig) -> None:
    print_rdp_x2go_info(config)
    print_success_header(config)
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
