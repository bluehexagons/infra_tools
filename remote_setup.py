#!/usr/bin/env python3
"""
Remote Setup Script

Usage (on the host):
    python3 remote_setup.py <system_type>                                    # Set up current user
    python3 remote_setup.py <system_type> <username>                         # Set up specified user
    python3 remote_setup.py <system_type> <username> <password>              # Set up user with password
    python3 remote_setup.py <system_type> <username> <password> <timezone>

System types:
    workstation_desktop - Full desktop workstation with RDP access
    server_dev          - Development server without desktop/RDP

Supported OS: Debian/Ubuntu, Fedora

When creating a new user without a password, generates a secure random password.

For backward compatibility, if the first argument is not a recognized system type,
it will default to 'workstation_desktop' and treat the first argument as username.
"""

import getpass
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os
from remote_modules.progress import progress_bar
from remote_modules.steps import STEPS, get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "server_dev"]


def main() -> int:
    timezone: Optional[str] = None
    pw: Optional[str] = None
    system_type: str = "workstation_desktop"
    
    # Parse arguments with backward compatibility
    if len(sys.argv) == 1:
        username = getpass.getuser()
    elif len(sys.argv) == 2:
        # Could be system_type or username (backward compat)
        if sys.argv[1] in VALID_SYSTEM_TYPES:
            system_type = sys.argv[1]
            username = getpass.getuser()
        else:
            username = sys.argv[1]
    elif len(sys.argv) == 3:
        # Could be (system_type, username) or (username, password)
        if sys.argv[1] in VALID_SYSTEM_TYPES:
            system_type = sys.argv[1]
            username = sys.argv[2]
        else:
            username = sys.argv[1]
            pw = sys.argv[2] if sys.argv[2] else None
    elif len(sys.argv) == 4:
        # Could be (system_type, username, password) or (username, password, timezone)
        if sys.argv[1] in VALID_SYSTEM_TYPES:
            system_type = sys.argv[1]
            username = sys.argv[2]
            pw = sys.argv[3] if sys.argv[3] else None
        else:
            username = sys.argv[1]
            pw = sys.argv[2] if sys.argv[2] else None
            timezone = sys.argv[3] if sys.argv[3] else None
    elif len(sys.argv) == 5:
        # system_type, username, password, timezone
        system_type = sys.argv[1]
        username = sys.argv[2]
        pw = sys.argv[3] if sys.argv[3] else None
        timezone = sys.argv[4] if sys.argv[4] else None
    else:
        print(f"Usage: {sys.argv[0]} [system_type] [username] [password] [timezone]")
        print(f"Valid system types: {', '.join(VALID_SYSTEM_TYPES)}")
        return 1
    
    if system_type not in VALID_SYSTEM_TYPES:
        print(f"Error: Invalid system type: {system_type}")
        print(f"Valid system types: {', '.join(VALID_SYSTEM_TYPES)}")
        return 1
    
    if not validate_username(username):
        print(f"Error: Invalid username format: {username}")
        return 1

    print("=" * 60)
    print(f"Remote Setup Script ({system_type})")
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

    steps = get_steps_for_system_type(system_type)
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
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
