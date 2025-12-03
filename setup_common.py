#!/usr/bin/env python3
"""
Common functionality shared between setup scripts.
"""

import getpass
import io
import os
import re
import shlex
import subprocess
import tarfile
from typing import Optional


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "remote_modules")
REMOTE_INSTALL_DIR = "/opt/infra_tools"


def validate_ip_address(ip: str) -> bool:
    """Validate IP address format."""
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_username(username: str) -> bool:
    """Validate username format."""
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def get_local_timezone() -> str:
    """Get the local machine's timezone."""
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
    """Get the current username."""
    return getpass.getuser()


def create_tar_archive() -> bytes:
    """Create a tar archive of the remote setup files."""
    tar_buffer = io.BytesIO()
    
    def safe_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        tarinfo.name = os.path.normpath(tarinfo.name)
        if tarinfo.name.startswith('..') or tarinfo.name.startswith('/'):
            return None
        return tarinfo
    
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        tar.add(REMOTE_SCRIPT_PATH, arcname="remote_setup.py", filter=safe_filter)
        tar.add(REMOTE_MODULES_DIR, arcname="remote_modules", filter=safe_filter)
    
    return tar_buffer.getvalue()


def run_remote_setup(
    ip: str,
    username: str,
    system_type: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
    timezone: Optional[str] = None,
) -> int:
    """Run the remote setup script on the target host."""
    try:
        tar_data = create_tar_archive()
    except FileNotFoundError as e:
        print(f"Error: Remote setup files not found: {e}")
        return 1
    
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    escaped_system_type = shlex.quote(system_type)
    escaped_username = shlex.quote(username)
    escaped_password = shlex.quote(password if password else "")
    escaped_timezone = shlex.quote(timezone if timezone else "")
    escaped_install_dir = shlex.quote(REMOTE_INSTALL_DIR)
    
    remote_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
python3 {escaped_install_dir}/remote_setup.py {escaped_system_type} {escaped_username} {escaped_password} {escaped_timezone}
"""
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", remote_cmd]
    
    try:
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
        
        process.stdin.write(tar_data)
        process.stdin.close()
        
        for line in io.TextIOWrapper(process.stdout, encoding='utf-8'):
            print(line, end='', flush=True)
        
        return process.wait()
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
