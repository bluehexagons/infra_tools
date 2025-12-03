#!/usr/bin/env python3
"""
Setup Remote Server for Development

Usage:
    python3 setup_server_dev.py [IP address]
    python3 setup_server_dev.py [IP address] [username]

Example:
    python3 setup_server_dev.py 192.168.1.100
    python3 setup_server_dev.py 192.168.1.100 johndoe
"""

import argparse
import os
import sys

from setup_common import (
    validate_ip_address,
    validate_username,
    get_local_timezone,
    get_current_username,
    run_remote_setup,
    REMOTE_SCRIPT_PATH,
    REMOTE_MODULES_DIR,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Setup a remote server for development",
        epilog="Example: python3 setup_server_dev.py 192.168.1.100 johndoe"
    )
    parser.add_argument("ip", help="IP address of the remote host")
    parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="Username for the sudo-enabled user (defaults to current user)"
    )
    parser.add_argument(
        "-k", "--key",
        help="Path to SSH private key (optional, uses default if not specified)"
    )
    parser.add_argument(
        "-p", "--password",
        help="Password for the user (only used when creating new user or updating existing)"
    )
    parser.add_argument(
        "-t", "--timezone",
        help="Timezone for the remote host (defaults to local machine's timezone)"
    )
    
    args = parser.parse_args()
    
    if not validate_ip_address(args.ip):
        print(f"Error: Invalid IP address format: {args.ip}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username format: {username}")
        print("Username must start with a lowercase letter or underscore,")
        print("contain only lowercase letters, numbers, underscores, or hyphens,")
        print("and be 32 characters or less.")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    if not os.path.exists(REMOTE_MODULES_DIR):
        print(f"Error: Remote modules directory not found: {REMOTE_MODULES_DIR}")
        return 1
    
    password = args.password
    
    timezone = args.timezone if args.timezone else get_local_timezone()
    
    print("=" * 60)
    print("Remote Server Development Setup")
    print("=" * 60)
    print(f"Target host: {args.ip}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    print("=" * 60)
    print()
    
    returncode = run_remote_setup(
        args.ip, username, "server_dev", password, args.key, timezone
    )
    
    if returncode != 0:
        print(f"\n✗ Remote setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"Server: {args.ip}")
    print(f"Username: {username}")
    print()
    print("Connect via SSH:")
    print(f"  ssh {username}@{args.ip}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
