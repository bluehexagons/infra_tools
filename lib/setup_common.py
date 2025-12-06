#!/usr/bin/env python3

import argparse
import getpass
import io
import os
import re
import shlex
import subprocess
import sys
import tarfile
from typing import Optional


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "..", "remote_modules")
REMOTE_INSTALL_DIR = "/opt/infra_tools"


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


def create_tar_archive() -> bytes:
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


def create_argument_parser(description: str, allow_steps: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("ip", help="IP address of the remote host")
    parser.add_argument("username", nargs="?", default=None, 
                       help="Username (defaults to current user)")
    parser.add_argument("-k", "--key", help="SSH private key path")
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to local)")
    if allow_steps:
        parser.add_argument("--steps", help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--skip-audio", action="store_true", 
                       help="Skip audio setup (desktop only)")
    parser.add_argument("--ruby", action="store_true",
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", action="store_true",
                       help="Install latest Go version")
    parser.add_argument("--node", action="store_true",
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    return parser


def run_remote_setup(
    ip: str,
    username: str,
    system_type: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
    timezone: Optional[str] = None,
    skip_audio: bool = False,
    install_ruby: bool = False,
    install_go: bool = False,
    install_node: bool = False,
    custom_steps: Optional[str] = None,
) -> int:
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
    
    escaped_install_dir = shlex.quote(REMOTE_INSTALL_DIR)
    
    cmd_parts = [
        f"python3 {escaped_install_dir}/remote_setup.py",
        f"--system-type {shlex.quote(system_type)}",
        f"--username {shlex.quote(username)}",
    ]
    
    if password:
        cmd_parts.append(f"--password {shlex.quote(password)}")
    
    if timezone:
        cmd_parts.append(f"--timezone {shlex.quote(timezone)}")
    
    if skip_audio:
        cmd_parts.append("--skip-audio")
    
    if install_ruby:
        cmd_parts.append("--ruby")
    
    if install_go:
        cmd_parts.append("--go")
    
    if install_node:
        cmd_parts.append("--node")
    
    if custom_steps:
        cmd_parts.append(f"--steps {shlex.quote(custom_steps)}")
    
    remote_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
{' '.join(cmd_parts)}
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


def setup_main(system_type: str, description: str, success_msg_fn) -> int:
    allow_steps = (system_type == "custom_steps")
    parser = create_argument_parser(description, allow_steps)
    args = parser.parse_args()
    
    if not validate_ip_address(args.ip):
        print(f"Error: Invalid IP address: {args.ip}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    if not os.path.exists(REMOTE_MODULES_DIR):
        print(f"Error: Remote modules not found: {REMOTE_MODULES_DIR}")
        return 1
    
    timezone = args.timezone if args.timezone else get_local_timezone()
    
    print("=" * 60)
    print(f"{description}")
    print("=" * 60)
    print(f"Host: {args.ip}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    if args.skip_audio and system_type == "workstation_desktop":
        print("Skip audio: Yes")
    if allow_steps and hasattr(args, 'steps') and args.steps:
        print(f"Steps: {args.steps}")
    print("=" * 60)
    print()
    
    custom_steps = args.steps if allow_steps and hasattr(args, 'steps') else None
    
    returncode = run_remote_setup(
        args.ip, username, system_type, args.password, args.key, 
        timezone, args.skip_audio, args.ruby, args.go, args.node, custom_steps
    )
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    success_msg_fn(args.ip, username)
    print("=" * 60)
    
    return 0
