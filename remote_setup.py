#!/usr/bin/env python3

import getpass
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os
from remote_modules.progress import progress_bar
from remote_modules.steps import get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "server_dev"]


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <system_type> [username] [password] [timezone] [skip_audio]")
        print(f"Valid system types: {', '.join(VALID_SYSTEM_TYPES)}")
        return 1
    
    system_type = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else getpass.getuser()
    pw: Optional[str] = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    timezone: Optional[str] = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
    skip_audio = len(sys.argv) > 5 and sys.argv[5] == "1"
    
    if system_type not in VALID_SYSTEM_TYPES:
        print(f"Error: Invalid system type: {system_type}")
        print(f"Valid system types: {', '.join(VALID_SYSTEM_TYPES)}")
        return 1
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1

    print("=" * 60)
    print(f"Remote Setup ({system_type})")
    print("=" * 60)
    print(f"User: {username}")
    print(f"Timezone: {timezone or 'UTC'}")
    if skip_audio:
        print("Skip audio: Yes")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"OS: {os_type}")
    sys.stdout.flush()

    steps = get_steps_for_system_type(system_type, skip_audio)
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
    print(f"\n{bar} Complete!")
    
    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
