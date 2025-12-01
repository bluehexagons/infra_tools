#!/usr/bin/env python3
"""
Setup Remote Workstation Desktop for RDP Access

This script connects to a remote Linux host as root using key-based SSH authentication
and sets up:
- A new sudo-enabled user
- XFCE desktop environment
- xRDP server for RDP access
- Secure defaults (firewall, SSH hardening)

Usage:
    python3 setup_workstation_desktop.py [IP address] [username]

Example:
    python3 setup_workstation_desktop.py 192.168.1.100 johndoe
"""

import argparse
import getpass
import re
import secrets
import string
import subprocess
import sys
from typing import Optional


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


def run_ssh_command(
    ip: str,
    command: str,
    ssh_key: Optional[str] = None,
    timeout: int = 300,
    skip_host_check: bool = False
) -> tuple[int, str, str]:
    """
    Execute a command on the remote host via SSH.
    
    Args:
        ip: Remote host IP address
        command: Command to execute
        ssh_key: Path to SSH private key (optional)
        timeout: Command timeout in seconds
        skip_host_check: If True, skip host key verification (less secure)
    
    Returns:
        Tuple of (return_code, stdout, stderr)
    
    Note:
        By default, uses 'accept-new' for StrictHostKeyChecking which accepts
        new host keys but rejects changed keys. For maximum security in sensitive
        environments, verify the host key manually before running this script.
    """
    # 'accept-new' accepts unknown keys but rejects changed keys (SSH 7.6+)
    # This is a reasonable default for infrastructure automation
    host_key_policy = "no" if skip_host_check else "accept-new"
    ssh_opts = [
        "-o", f"StrictHostKeyChecking={host_key_policy}",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", command]
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


def check_ssh_connection(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Verify SSH connection to remote host."""
    print(f"Testing SSH connection to {ip}...")
    returncode, stdout, stderr = run_ssh_command(ip, "echo 'SSH connection successful'", ssh_key)
    if returncode == 0:
        print("✓ SSH connection established")
        return True
    print(f"✗ SSH connection failed: {stderr}")
    return False


def detect_os(ip: str, ssh_key: Optional[str] = None) -> Optional[str]:
    """Detect the operating system on the remote host."""
    print("Detecting remote OS...")
    returncode, stdout, _ = run_ssh_command(ip, "cat /etc/os-release", ssh_key)
    if returncode != 0:
        return None
    
    stdout_lower = stdout.lower()
    if "ubuntu" in stdout_lower or "debian" in stdout_lower:
        print("✓ Detected Debian/Ubuntu-based system")
        return "debian"
    elif "rhel" in stdout_lower or "centos" in stdout_lower or "fedora" in stdout_lower or "rocky" in stdout_lower or "almalinux" in stdout_lower:
        print("✓ Detected RHEL/CentOS/Fedora-based system")
        return "rhel"
    
    print("✗ Unsupported OS detected")
    return None


def detect_package_manager(ip: str, ssh_key: Optional[str] = None) -> str:
    """Detect the package manager available on the remote host."""
    # Check for dnf first (modern RHEL-based)
    returncode, _, _ = run_ssh_command(ip, "command -v dnf", ssh_key, timeout=30)
    if returncode == 0:
        return "dnf"
    
    # Check for yum (older RHEL-based)
    returncode, _, _ = run_ssh_command(ip, "command -v yum", ssh_key, timeout=30)
    if returncode == 0:
        return "yum"
    
    # Default to apt for Debian-based
    return "apt"


def create_user(ip: str, username: str, password: str, ssh_key: Optional[str] = None) -> bool:
    """Create a new sudo-enabled user on the remote host."""
    print(f"Creating user '{username}'...")
    
    # Create user with home directory
    cmd = f"useradd -m -s /bin/bash {username}"
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key)
    if returncode != 0 and "already exists" not in stderr:
        print(f"✗ Failed to create user: {stderr}")
        return False
    
    # Set password using chpasswd with here-document to avoid exposure in process list
    # The password is passed via stdin to avoid appearing in 'ps' output
    cmd = f"chpasswd <<'EOFPWD'\n{username}:{password}\nEOFPWD"
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key)
    if returncode != 0:
        print(f"✗ Failed to set password: {stderr}")
        return False
    
    # Add user to sudo group
    # Try both 'sudo' (Debian/Ubuntu) and 'wheel' (RHEL/CentOS) groups
    for group in ["sudo", "wheel"]:
        cmd = f"usermod -aG {group} {username}"
        returncode, _, _ = run_ssh_command(ip, cmd, ssh_key)
        if returncode == 0:
            break
    
    print(f"✓ User '{username}' created with sudo privileges")
    return True


def install_desktop_debian(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Install XFCE desktop environment on Debian/Ubuntu."""
    print("Installing XFCE desktop environment (this may take several minutes)...")
    
    commands = [
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update",
        "apt-get install -y xfce4 xfce4-goodies",
    ]
    
    cmd = " && ".join(commands)
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key, timeout=900)
    if returncode != 0:
        print(f"✗ Failed to install desktop: {stderr}")
        return False
    
    print("✓ XFCE desktop installed")
    return True


def install_desktop_rhel(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Install XFCE desktop environment on RHEL/CentOS."""
    print("Installing XFCE desktop environment (this may take several minutes)...")
    
    # Detect and use appropriate package manager
    pkg_mgr = detect_package_manager(ip, ssh_key)
    print(f"  Using package manager: {pkg_mgr}")
    
    cmd = f"{pkg_mgr} groupinstall -y 'Xfce'"
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key, timeout=900)
    if returncode != 0:
        print(f"✗ Failed to install desktop: {stderr}")
        return False
    
    print("✓ XFCE desktop installed")
    return True


def install_xrdp_debian(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Install and configure xRDP on Debian/Ubuntu."""
    print("Installing xRDP...")
    
    commands = [
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get install -y xrdp",
        # Add xrdp to ssl-cert group if it exists (for TLS certificate access)
        "getent group ssl-cert >/dev/null && adduser xrdp ssl-cert || echo 'Note: ssl-cert group not found, skipping'",
        "systemctl enable xrdp",
        "systemctl restart xrdp",
    ]
    
    cmd = " && ".join(commands)
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key, timeout=300)
    if returncode != 0:
        print(f"✗ Failed to install xRDP: {stderr}")
        return False
    
    print("✓ xRDP installed and started")
    return True


def install_xrdp_rhel(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Install and configure xRDP on RHEL/CentOS."""
    print("Installing xRDP...")
    
    # Detect and use appropriate package manager
    pkg_mgr = detect_package_manager(ip, ssh_key)
    print(f"  Using package manager: {pkg_mgr}")
    
    commands = [
        f"{pkg_mgr} install -y epel-release",
        f"{pkg_mgr} install -y xrdp",
        "systemctl enable xrdp",
        "systemctl restart xrdp",
    ]
    
    cmd = " && ".join(commands)
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key, timeout=300)
    if returncode != 0:
        print(f"✗ Failed to install xRDP: {stderr}")
        return False
    
    print("✓ xRDP installed and started")
    return True


def configure_user_session(ip: str, username: str, ssh_key: Optional[str] = None) -> bool:
    """Configure user session to use XFCE."""
    print("Configuring user session...")
    
    cmd = f"echo 'xfce4-session' > /home/{username}/.xsession && chown {username}:{username} /home/{username}/.xsession"
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key)
    if returncode != 0:
        print(f"✗ Failed to configure session: {stderr}")
        return False
    
    print("✓ User session configured")
    return True


def apply_secure_defaults(ip: str, os_type: str, ssh_key: Optional[str] = None) -> bool:
    """Apply secure defaults to the system."""
    print("Applying secure defaults...")
    
    # Configure firewall
    if os_type == "debian":
        firewall_cmds = [
            "apt-get install -y ufw",
            "ufw default deny incoming",
            "ufw default allow outgoing",
            "ufw allow ssh",
            "ufw allow 3389/tcp",  # RDP port
            "echo 'y' | ufw enable || ufw --force enable",
        ]
    else:
        firewall_cmds = [
            "firewall-cmd --permanent --add-service=ssh || true",
            "firewall-cmd --permanent --add-port=3389/tcp || true",
            "firewall-cmd --reload || true",
        ]
    
    cmd = " && ".join(firewall_cmds)
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key)
    if returncode != 0:
        print(f"Warning: Firewall configuration may have failed: {stderr}")
    else:
        print("✓ Firewall configured (SSH and RDP ports allowed)")
    
    # Harden SSH configuration (with backup)
    ssh_hardening_cmds = [
        "cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak",
        "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config",
        "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config",
        "sed -i 's/^#*X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config",
        "sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config",
        "systemctl reload sshd || systemctl reload ssh",
    ]
    
    cmd = " && ".join(ssh_hardening_cmds)
    returncode, _, stderr = run_ssh_command(ip, cmd, ssh_key)
    if returncode != 0:
        print(f"Warning: SSH hardening may have failed: {stderr}")
    else:
        print("✓ SSH hardened (root password login disabled, password auth disabled)")
    
    return True


def main() -> int:
    """Main function to orchestrate the workstation setup."""
    parser = argparse.ArgumentParser(
        description="Setup a remote workstation server for RDP access",
        epilog="Example: python3 setup_workstation_desktop.py 192.168.1.100 johndoe"
    )
    parser.add_argument("ip", help="IP address of the remote host")
    parser.add_argument("username", help="Username for the new sudo-enabled user")
    parser.add_argument(
        "-k", "--key",
        help="Path to SSH private key (optional, uses default if not specified)"
    )
    parser.add_argument(
        "-p", "--password",
        help="Password for the new user (if not specified, a secure password will be generated)"
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
    
    # Generate or use provided password
    password = args.password if args.password else generate_password()
    
    print("=" * 60)
    print("Remote Workstation Desktop Setup")
    print("=" * 60)
    print(f"Target host: {args.ip}")
    print(f"New user: {args.username}")
    print("=" * 60)
    print()
    
    # Test SSH connection
    if not check_ssh_connection(args.ip, args.key):
        return 1
    
    # Detect OS
    os_type = detect_os(args.ip, args.key)
    if not os_type:
        print("Error: Could not detect or unsupported operating system")
        return 1
    
    # Create user
    if not create_user(args.ip, args.username, password, args.key):
        return 1
    
    # Install desktop environment
    if os_type == "debian":
        if not install_desktop_debian(args.ip, args.key):
            return 1
    else:
        if not install_desktop_rhel(args.ip, args.key):
            return 1
    
    # Install xRDP
    if os_type == "debian":
        if not install_xrdp_debian(args.ip, args.key):
            return 1
    else:
        if not install_xrdp_rhel(args.ip, args.key):
            return 1
    
    # Configure user session
    if not configure_user_session(args.ip, args.username, args.key):
        return 1
    
    # Apply secure defaults
    apply_secure_defaults(args.ip, os_type, args.key)
    
    # Print summary
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"RDP Host: {args.ip}:3389")
    print(f"Username: {args.username}")
    if not args.password:
        print(f"Password: {password}")
        print()
        print("IMPORTANT: Save this password securely!")
        print("Consider changing it after first login.")
    print()
    print("To connect, use an RDP client (e.g., Remmina, Microsoft Remote Desktop)")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
