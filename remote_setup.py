#!/usr/bin/env python3
"""
Remote Workstation Setup Script

Usage (on the host):
    python3 remote_setup.py                           # Set up current user
    python3 remote_setup.py <username>                # Set up specified user
    python3 remote_setup.py <username> <password>     # Set up user with password
    python3 remote_setup.py <username> <password> <timezone>

Supported OS: Debian/Ubuntu, Fedora

When creating a new user without a password, generates a secure random password.
"""

import getpass
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os
from remote_modules.progress import progress_bar
from remote_modules.steps import STEPS


def main() -> int:
    timezone: Optional[str] = None
    pw: Optional[str] = None
    
    if len(sys.argv) == 1:
        username = getpass.getuser()
    elif len(sys.argv) == 2:
        username = sys.argv[1]
    elif len(sys.argv) == 3:
        username = sys.argv[1]
        pw = sys.argv[2] if sys.argv[2] else None
    elif len(sys.argv) == 4:
        username = sys.argv[1]
        pw = sys.argv[2] if sys.argv[2] else None
        timezone = sys.argv[3] if sys.argv[3] else None
    else:
        print(f"Usage: {sys.argv[0]} [username] [password] [timezone]")
        return 1
    
    if not validate_username(username):
        print(f"Error: Invalid username format: {username}")
        return 1

    print("=" * 60)
    print("Remote Workstation Setup Script")
    print("=" * 60)
    print(f"Target user: {username}")
    if timezone:
        print(f"Timezone: {timezone}")
    else:
        print("Timezone: UTC (default)")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"Detected OS type: {os_type}")
    sys.stdout.flush()

    total_steps = len(STEPS)
    for i, (name, func) in enumerate(STEPS, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        func(
            username=username,
            password=pw,
            os_type=os_type,
            timezone=timezone
        )
    
    bar = progress_bar(total_steps, total_steps)
    print(f"\n{bar} All steps completed!")
    
    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
