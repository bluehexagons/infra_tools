#!/usr/bin/env python3
"""
Setup Remote Workstation Desktop for RDP Access

Usage:
    python3 setup_workstation_desktop.py [IP address]
    python3 setup_workstation_desktop.py [IP address] [username]

Example:
    python3 setup_workstation_desktop.py 192.168.1.100
    python3 setup_workstation_desktop.py 192.168.1.100 johndoe
"""

import argparse
import getpass
import os
import re
import shlex
import subprocess
import sys
from typing import Optional


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "remote_modules")


def validate_ip_address(ip: str) -> bool:
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_username(username: str) -> bool:
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def get_local_timezone() -> str:
    if os.path.exists("/etc/timezone"):
        try:
            with open("/etc/timezone", "r") as f:
                tz = f.read().strip()
                if tz:
                    return tz
        except Exception:
            pass
    
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    
    if os.path.islink("/etc/localtime"):
        try:
            target = os.readlink("/etc/localtime")
            if "zoneinfo/" in target:
                tz = target.split("zoneinfo/", 1)[1]
                return tz
        except Exception:
            pass
    
    return "UTC"


def get_current_username() -> str:
    return getpass.getuser()


def build_remote_script() -> str:
    modules_content = {}
    
    for module_name in ["__init__", "utils", "progress", "steps"]:
        module_path = os.path.join(REMOTE_MODULES_DIR, f"{module_name}.py")
        if os.path.exists(module_path):
            with open(module_path, "r") as f:
                modules_content[module_name] = f.read()
    
    with open(REMOTE_SCRIPT_PATH, "r") as f:
        main_script = f.read()
    
    combined_script = '''#!/usr/bin/env python3
"""Combined remote setup script (auto-generated)."""
import sys
import os

# Create temporary module structure
import tempfile
import importlib.util

_temp_dir = tempfile.mkdtemp(prefix="remote_modules_")
_modules_dir = os.path.join(_temp_dir, "remote_modules")
os.makedirs(_modules_dir)

'''
    
    for module_name, content in modules_content.items():
        escaped_content = content.replace('\\', '\\\\').replace("'''", "\\'\\'\\'")
        combined_script += f'''
with open(os.path.join(_modules_dir, "{module_name}.py"), "w") as f:
    f.write(\'\'\'{escaped_content}\'\'\')
'''
    
    combined_script += '''
sys.path.insert(0, _temp_dir)

'''
    
    main_script_lines = main_script.split('\n')
    skip_shebang = False
    for line in main_script_lines:
        if line.startswith('#!'):
            skip_shebang = True
            continue
        if skip_shebang and line.strip() == '':
            skip_shebang = False
            continue
        combined_script += line + '\n'
    
    combined_script += '''
# Cleanup temp directory
import shutil
try:
    shutil.rmtree(_temp_dir)
except:
    pass
'''
    
    return combined_script


def run_remote_setup(
    ip: str,
    username: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
    timezone: Optional[str] = None,
) -> tuple[int, Optional[str]]:
    try:
        script_content = build_remote_script()
    except FileNotFoundError as e:
        print(f"Error: Remote setup script not found: {e}")
        return 1, None
    
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    escaped_username = shlex.quote(username)
    escaped_password = shlex.quote(password if password else "")
    escaped_timezone = shlex.quote(timezone if timezone else "")
    remote_cmd = f"python3 - {escaped_username} {escaped_password} {escaped_timezone}"
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", remote_cmd]
    
    generated_password = None
    
    try:
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        process.stdin.write(script_content)
        process.stdin.close()
        
        for line in process.stdout:
            if line.startswith("GENERATED_PASSWORD:"):
                generated_password = line.strip().split(":", 1)[1]
            else:
                print(line, end='', flush=True)
        
        return_code = process.wait()
        return return_code, generated_password
        
    except Exception as e:
        print(f"Error: {e}")
        return 1, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Setup a remote workstation server for RDP access",
        epilog="Example: python3 setup_workstation_desktop.py 192.168.1.100 johndoe"
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
        help="Password for the user (if not specified, a secure password will be generated)"
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
    print("Remote Workstation Desktop Setup")
    print("=" * 60)
    print(f"Target host: {args.ip}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    print("=" * 60)
    print()
    
    returncode, generated_password = run_remote_setup(
        args.ip, username, password, args.key, timezone
    )
    
    if returncode != 0:
        print(f"\n✗ Remote setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"RDP Host: {args.ip}:3389")
    print(f"Username: {username}")
    if password:
        print("Password: (as specified)")
    elif generated_password:
        print(f"Password: {generated_password}")
        print()
        print("IMPORTANT: Save this password securely!")
    else:
        print("Password: unchanged")
    print()
    print("Connect using an RDP client (e.g., Remmina, Microsoft Remote Desktop)")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
