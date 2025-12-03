#!/usr/bin/env python3

import argparse
import getpass
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os
from remote_modules.progress import progress_bar
from remote_modules.steps import get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "workstation_dev", "server_dev", "server_web"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Remote system setup")
    parser.add_argument("--system-type", required=True, 
                       choices=VALID_SYSTEM_TYPES,
                       help="System type to setup")
    parser.add_argument("--username", default=None,
                       help="Username (defaults to current user)")
    parser.add_argument("--password", default=None,
                       help="User password")
    parser.add_argument("--timezone", default=None,
                       help="Timezone (defaults to UTC)")
    parser.add_argument("--skip-audio", action="store_true",
                       help="Skip audio setup")
    
    args = parser.parse_args()
    
    username = args.username or getpass.getuser()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1

    print("=" * 60)
    print(f"Remote Setup ({args.system_type})")
    print("=" * 60)
    print(f"User: {username}")
    print(f"Timezone: {args.timezone or 'UTC'}")
    if args.skip_audio:
        print("Skip audio: Yes")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"OS: {os_type}")
    sys.stdout.flush()

    steps = get_steps_for_system_type(args.system_type, args.skip_audio)
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        func(
            username=username,
            pw=args.password,
            os_type=os_type,
            timezone=args.timezone
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
