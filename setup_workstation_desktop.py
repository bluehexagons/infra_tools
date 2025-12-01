#!/usr/bin/env python3
"""
Setup Remote Workstation Desktop for RDP Access

This script connects to a remote Linux host as root using key-based SSH authentication
and sets up:
- A new sudo-enabled user
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


def get_ssh_options(ssh_key: Optional[str] = None) -> list[str]:
    """Get common SSH options."""
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    return ssh_opts


def run_ssh_command(
    ip: str,
    command: str,
    ssh_key: Optional[str] = None,
    timeout: int = 300
) -> tuple[int, str, str]:
    """
    Execute a command on the remote host via SSH.
    
    Args:
        ip: Remote host IP address
        command: Command to execute
        ssh_key: Path to SSH private key (optional)
        timeout: Command timeout in seconds
    
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    ssh_opts = get_ssh_options(ssh_key)
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


def transfer_and_run_script(
    ip: str,
    script: str,
    ssh_key: Optional[str] = None,
    timeout: int = 1800
) -> tuple[int, str, str]:
    """
    Transfer a Python script to the remote host and execute it.
    
    Args:
        ip: Remote host IP address
        script: Python script content to execute
        ssh_key: Path to SSH private key (optional)
        timeout: Execution timeout in seconds
    
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    ssh_opts = get_ssh_options(ssh_key)
    
    # Use ssh to pipe script directly to python3 on remote host
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", "python3 -"]
    
    try:
        result = subprocess.run(
            ssh_cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Script execution timed out"
    except Exception as e:
        return 1, "", str(e)


def check_ssh_connection(ip: str, ssh_key: Optional[str] = None) -> bool:
    """Verify SSH connection to remote host."""
    print(f"Testing SSH connection to {ip}...")
    returncode, _, stderr = run_ssh_command(
        ip, "echo 'SSH connection successful'", ssh_key
    )
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
    elif "fedora" in stdout_lower:
        print("✓ Detected Fedora system")
        return "fedora"
    
    print("✗ Unsupported OS detected (only Debian/Ubuntu and Fedora are supported)")
    return None


def generate_remote_setup_script(username: str, password: str, os_type: str) -> str:
    """Generate the Python script to run on the remote host."""
    
    # Escape special characters in password for shell safety
    escaped_password = password.replace("'", "'\"'\"'")
    
    script = f'''#!/usr/bin/env python3
"""Remote workstation setup script - runs on the target host."""

import subprocess
import sys
import os

def run(cmd, check=True, shell=True):
    """Run a command and return the result."""
    print(f"  Running: {{cmd[:80]}}..." if len(cmd) > 80 else f"  Running: {{cmd}}")
    result = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"    Warning: {{result.stderr[:200]}}" if result.stderr else "    (no stderr)")
    return result

def main():
    username = "{username}"
    password = '{escaped_password}'
    os_type = "{os_type}"
    
    print("=" * 60)
    print("Remote Workstation Setup Script")
    print("=" * 60)
    
    # =========================================================================
    # 1. Create user with sudo privileges
    # =========================================================================
    print("\\n[1/8] Creating user...")
    
    result = run(f"id {{username}}", check=False)
    if result.returncode != 0:
        run(f"useradd -m -s /bin/bash {{username}}")
    
    # Set password using chpasswd
    process = subprocess.run(
        ["chpasswd"],
        input=f"{{username}}:{{password}}\\n",
        text=True,
        capture_output=True
    )
    if process.returncode != 0:
        print(f"  Warning: Failed to set password: {{process.stderr}}")
    
    # Add to sudo/wheel group
    if os_type == "debian":
        run(f"usermod -aG sudo {{username}}", check=False)
    else:
        run(f"usermod -aG wheel {{username}}", check=False)
    
    print("  ✓ User created with sudo privileges")
    
    # =========================================================================
    # 2. Configure time synchronization (NTP)
    # =========================================================================
    print("\\n[2/8] Configuring time synchronization...")
    
    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get update -qq")
        run("apt-get install -y -qq systemd-timesyncd")
        run("timedatectl set-ntp true")
    else:
        run("dnf install -y -q chrony")
        run("systemctl enable chronyd")
        run("systemctl start chronyd")
    
    # Set timezone to UTC as a sensible default
    run("timedatectl set-timezone UTC")
    print("  ✓ Time synchronization configured (NTP enabled, timezone: UTC)")
    
    # =========================================================================
    # 3. Install desktop environment (XFCE)
    # =========================================================================
    print("\\n[3/8] Installing XFCE desktop environment...")
    print("  (This may take several minutes)")
    
    if os_type == "debian":
        run("apt-get install -y -qq xfce4 xfce4-goodies")
    else:
        run("dnf groupinstall -y 'Xfce Desktop'")
    
    print("  ✓ XFCE desktop installed")
    
    # =========================================================================
    # 4. Install and configure xRDP
    # =========================================================================
    print("\\n[4/8] Installing xRDP...")
    
    if os_type == "debian":
        run("apt-get install -y -qq xrdp")
        # Add xrdp to ssl-cert group if it exists
        run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    else:
        run("dnf install -y -q xrdp")
    
    run("systemctl enable xrdp")
    run("systemctl restart xrdp")
    
    # Configure user session
    xsession_path = f"/home/{{username}}/.xsession"
    with open(xsession_path, "w") as f:
        f.write("xfce4-session\\n")
    run(f"chown {{username}}:{{username}} {{xsession_path}}")
    
    print("  ✓ xRDP installed and configured")
    
    # =========================================================================
    # 5. Configure firewall
    # =========================================================================
    print("\\n[5/8] Configuring firewall...")
    
    if os_type == "debian":
        run("apt-get install -y -qq ufw")
        run("ufw default deny incoming")
        run("ufw default allow outgoing")
        run("ufw allow ssh")
        run("ufw allow 3389/tcp")
        run("ufw --force enable")
    else:
        run("systemctl enable firewalld", check=False)
        run("systemctl start firewalld", check=False)
        run("firewall-cmd --permanent --add-service=ssh", check=False)
        run("firewall-cmd --permanent --add-port=3389/tcp", check=False)
        run("firewall-cmd --reload", check=False)
    
    print("  ✓ Firewall configured (SSH and RDP allowed)")
    
    # =========================================================================
    # 6. Install and configure fail2ban for RDP protection
    # =========================================================================
    print("\\n[6/8] Installing fail2ban for RDP brute-force protection...")
    
    if os_type == "debian":
        run("apt-get install -y -qq fail2ban")
    else:
        run("dnf install -y -q fail2ban")
    
    # Configure fail2ban for xrdp
    fail2ban_xrdp_filter = """[Definition]
failregex = ^.*xrdp-sesman.*: .*login failed for user.*from ip <HOST>.*$
            ^.*xrdp.*: .*connection from <HOST>.*failed.*$
ignoreregex =
"""
    
    fail2ban_xrdp_jail = """[xrdp]
enabled = true
port = 3389
protocol = tcp
filter = xrdp
logpath = /var/log/xrdp-sesman.log
maxretry = 3
bantime = 3600
findtime = 600
"""
    
    # Write filter
    with open("/etc/fail2ban/filter.d/xrdp.conf", "w") as f:
        f.write(fail2ban_xrdp_filter)
    
    # Write jail
    with open("/etc/fail2ban/jail.d/xrdp.local", "w") as f:
        f.write(fail2ban_xrdp_jail)
    
    run("systemctl enable fail2ban")
    run("systemctl restart fail2ban")
    
    print("  ✓ fail2ban configured (3 failed attempts = 1 hour ban)")
    
    # =========================================================================
    # 7. Harden SSH configuration
    # =========================================================================
    print("\\n[7/8] Hardening SSH configuration...")
    
    # Backup original config
    run("cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak")
    
    ssh_hardening = [
        ("PermitRootLogin", "prohibit-password"),
        ("PasswordAuthentication", "no"),
        ("X11Forwarding", "no"),
        ("MaxAuthTries", "3"),
    ]
    
    for ssh_key, ssh_value in ssh_hardening:
        run(f"sed -i 's/^#*{{ssh_key}}.*/{{ssh_key}} {{ssh_value}}/' /etc/ssh/sshd_config")
    
    run("systemctl reload sshd || systemctl reload ssh", check=False)
    
    print("  ✓ SSH hardened (key-only auth, no root password, max 3 attempts)")
    
    # =========================================================================
    # 8. Configure automatic security updates
    # =========================================================================
    print("\\n[8/8] Configuring automatic security updates...")
    
    if os_type == "debian":
        run("apt-get install -y -qq unattended-upgrades")
        
        # Enable automatic updates
        auto_upgrades = """APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
"""
        with open("/etc/apt/apt.conf.d/20auto-upgrades", "w") as f:
            f.write(auto_upgrades)
        
        run("systemctl enable unattended-upgrades")
        run("systemctl start unattended-upgrades")
    else:
        run("dnf install -y -q dnf-automatic")
        
        # Configure dnf-automatic for security updates
        run("sed -i 's/apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf")
        run("sed -i 's/upgrade_type = default/upgrade_type = security/' /etc/dnf/automatic.conf")
        
        run("systemctl enable dnf-automatic.timer")
        run("systemctl start dnf-automatic.timer")
    
    print("  ✓ Automatic security updates enabled")
    
    # =========================================================================
    # Done
    # =========================================================================
    print("\\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    return script


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
    
    # Generate and transfer the setup script
    print("\nTransferring setup script to remote host...")
    remote_script = generate_remote_setup_script(args.username, password, os_type)
    
    print("Executing remote setup (this may take 10-15 minutes)...\n")
    returncode, stdout, stderr = transfer_and_run_script(
        args.ip, remote_script, args.key, timeout=1800
    )
    
    # Print remote script output
    if stdout:
        print(stdout)
    
    if returncode != 0:
        print(f"\n✗ Remote setup failed")
        if stderr:
            print(f"Error: {stderr}")
        return 1
    
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
