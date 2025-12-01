#!/usr/bin/env python3
"""
Setup Remote Workstation Desktop for RDP Access

This script connects to a remote Linux host as root using key-based SSH authentication
and sets up:
- A new sudo-enabled user (or configures an existing one)
- XFCE desktop environment
- xRDP server for RDP access
- Secure defaults (firewall, SSH hardening, fail2ban for RDP)
- NTP time synchronization
- Automatic security updates

Usage:
    python3 setup_workstation_desktop.py [IP address] [username]

Example:
    python3 setup_workstation_desktop.py 192.168.1.100 johndoe
"""

import argparse
import os
import re
import secrets
import shlex
import string
import subprocess
import sys
from typing import Optional


# Path to the remote setup script (in the same directory as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "remote_setup.py")


def validate_ip_address(ip: str) -> bool:
    """Validate IPv4 address format."""
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_username(username: str) -> bool:
    """Validate username format (lowercase letters, numbers, underscore, hyphen)."""
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def generate_password(length: int = 16) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def run_remote_setup(
    ip: str,
    username: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
) -> int:
    """
    Transfer and run the remote setup script on the target host.
    Streams stdout in real-time.
    
    Args:
        ip: Remote host IP address
        username: Username to create/configure
        password: Password for the user (optional)
        ssh_key: Path to SSH private key (optional)
    
    Returns:
        Return code from remote script
    """
    # Read the remote setup script
    try:
        with open(REMOTE_SCRIPT_PATH, "r") as f:
            script_content = f.read()
    except FileNotFoundError:
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    # Build SSH options
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    # Build remote command with arguments
    escaped_username = shlex.quote(username)
    if password:
        escaped_password = shlex.quote(password)
        remote_cmd = f"python3 - {escaped_username} {escaped_password}"
    else:
        remote_cmd = f"python3 - {escaped_username}"
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", remote_cmd]
    
    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        
        # Send script content to stdin
        process.stdin.write(script_content)
        process.stdin.close()
        
        # Stream stdout line by line
        for line in process.stdout:
            print(line, end='', flush=True)
        
        # Wait for process to complete
        return_code = process.wait()
        return return_code
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def main() -> int:
    """Main function to orchestrate the workstation setup."""
    parser = argparse.ArgumentParser(
        description="Setup a remote workstation server for RDP access",
        epilog="Example: python3 setup_workstation_desktop.py 192.168.1.100 johndoe"
    )
    parser.add_argument("ip", help="IP address of the remote host")
    parser.add_argument("username", help="Username for the sudo-enabled user")
    parser.add_argument(
        "-k", "--key",
        help="Path to SSH private key (optional, uses default if not specified)"
    )
    parser.add_argument(
        "-p", "--password",
        help="Password for the user (if not specified, a secure password will be generated)"
    )
    parser.add_argument(
        "--no-password",
        action="store_true",
        help="Don't set/change password (useful for existing users)"
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not validate_ip_address(args.ip):
        print(f"Error: Invalid IP address format: {args.ip}")
        return 1
    
    if not validate_username(args.username):
        print(f"Error: Invalid username format: {args.username}")
        print("Username must start with a lowercase letter or underscore,")
        print("contain only lowercase letters, numbers, underscores, or hyphens,")
        print("and be 32 characters or less.")
        return 1
    
    # Verify remote script exists
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    # Determine password handling
    if args.no_password:
        password = None
        show_password = False
    elif args.password:
        password = args.password
        show_password = False
    else:
        password = generate_password()
        show_password = True
    
    print("=" * 60)
    print("Remote Workstation Desktop Setup")
    print("=" * 60)
    print(f"Target host: {args.ip}")
    print(f"User: {args.username}")
    print("Script is idempotent - safe to run multiple times.")
    print("=" * 60)
    print()
    
    # Run the remote setup (streams output in real-time)
    returncode = run_remote_setup(
        args.ip, args.username, password, args.key
    )
    
    if returncode != 0:
        print(f"\n✗ Remote setup failed (exit code: {returncode})")
        return 1
    
    # Print summary
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"RDP Host: {args.ip}:3389")
    print(f"Username: {args.username}")
    if show_password and password:
        print(f"Password: {password}")
        print()
        print("IMPORTANT: Save this password securely!")
        print("Consider changing it after first login.")
    print()
    print("Security features enabled:")
    print("  • Firewall (SSH and RDP ports only)")
    print("  • fail2ban (3 failed RDP logins = 1 hour ban)")
    print("  • SSH hardening (key-only auth)")
    print("  • NTP time sync")
    print("  • Automatic security updates")
    print()
    print("To connect, use an RDP client (e.g., Remmina, Microsoft Remote Desktop)")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
