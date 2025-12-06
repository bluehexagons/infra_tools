#!/usr/bin/env python3

import argparse
import getpass
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os
from remote_modules.progress import progress_bar
from remote_modules.system_types import get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "workstation_dev", "server_dev", "server_web", "server_proxmox", "custom_steps"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Remote system setup")
    parser.add_argument("--system-type", required=False,
                       choices=VALID_SYSTEM_TYPES,
                       help="System type to setup")
    parser.add_argument("--steps", default=None,
                       help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--username", default=None,
                       help="Username (defaults to current user, not used for server_proxmox)")
    parser.add_argument("--password", default=None,
                       help="User password (not used for server_proxmox)")
    parser.add_argument("--timezone", default=None,
                       help="Timezone (defaults to UTC)")
    parser.add_argument("--skip-audio", action="store_true",
                       help="Skip audio setup")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"], default="xfce",
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--ruby", action="store_true",
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", action="store_true",
                       help="Install latest Go version")
    parser.add_argument("--node", action="store_true",
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    
    args = parser.parse_args()
    
    if args.steps:
        system_type = "custom_steps"
    elif args.system_type:
        system_type = args.system_type
    else:
        print("Error: Either --system-type or --steps must be specified")
        return 1
    
    if system_type == "server_proxmox":
        username = "root"
    else:
        username = args.username or getpass.getuser()
        if not validate_username(username):
            print(f"Error: Invalid username: {username}")
            return 1

    print("=" * 60)
    print(f"Remote Setup ({system_type})")
    print("=" * 60)
    if system_type != "server_proxmox":
        print(f"User: {username}")
    print(f"Timezone: {args.timezone or 'UTC'}")
    if args.skip_audio:
        print("Skip audio: Yes")
    if args.desktop != "xfce" and system_type in ["workstation_desktop", "workstation_dev"]:
        print(f"Desktop: {args.desktop}")
    if args.steps:
        print(f"Steps: {args.steps}")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"OS: {os_type}")
    sys.stdout.flush()

    steps = get_steps_for_system_type(system_type, args.skip_audio, args.desktop, args.ruby, args.go, args.node, args.steps)
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        func(
            username=username,
            pw=args.password,
            os_type=os_type,
            timezone=args.timezone,
            desktop=args.desktop
        )
    
    bar = progress_bar(total_steps, total_steps)
    print(f"\n{bar} Complete!")
    
    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
