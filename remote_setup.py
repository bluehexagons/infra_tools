#!/usr/bin/env python3
"""
Remote Workstation Setup Script

This script runs on the target host to set up:
- A new sudo-enabled user
- XFCE desktop environment
- xRDP server for RDP access
- Secure defaults (firewall, SSH hardening, fail2ban for RDP)
- NTP time synchronization
- Automatic security updates

Usage (on remote host):
    python3 remote_setup.py <username> <password>

Supported OS: Debian/Ubuntu, Fedora
"""

import os
import re
import shlex
import subprocess
import sys


def validate_username(username: str) -> bool:
    """Validate username format (lowercase letters, numbers, underscore, hyphen)."""
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    print(f"  Running: {cmd[:80]}..." if len(cmd) > 80 else f"  Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(f"    Warning: {result.stderr[:200]}")
    return result


def detect_os() -> str:
    """Detect the operating system."""
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
    except FileNotFoundError:
        print("Error: Cannot detect OS - /etc/os-release not found")
        sys.exit(1)

    if "ubuntu" in content or "debian" in content:
        return "debian"
    elif "fedora" in content:
        return "fedora"
    else:
        print("Error: Unsupported OS (only Debian/Ubuntu and Fedora are supported)")
        sys.exit(1)


def create_user(username: str, password: str, os_type: str) -> None:
    """Create user with sudo privileges."""
    print("\n[1/8] Creating user...")
    
    # Use shlex.quote for safe shell interpolation
    safe_username = shlex.quote(username)

    result = run(f"id {safe_username}", check=False)
    if result.returncode != 0:
        run(f"useradd -m -s /bin/bash {safe_username}")

    # Set password using chpasswd via stdin (safe - no shell interpolation)
    process = subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        capture_output=True
    )
    if process.returncode != 0:
        print(f"  Warning: Failed to set password: {process.stderr}")

    # Add to sudo/wheel group
    if os_type == "debian":
        run(f"usermod -aG sudo {safe_username}", check=False)
    else:
        run(f"usermod -aG wheel {safe_username}", check=False)

    print("  ✓ User created with sudo privileges")


def configure_time_sync(os_type: str) -> None:
    """Configure NTP time synchronization."""
    print("\n[2/8] Configuring time synchronization...")

    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get update -qq")
        run("apt-get install -y -qq systemd-timesyncd")
        run("timedatectl set-ntp true")
    else:
        run("dnf install -y -q chrony")
        run("systemctl enable chronyd")
        run("systemctl start chronyd")

    run("timedatectl set-timezone UTC")
    print("  ✓ Time synchronization configured (NTP enabled, timezone: UTC)")


def install_desktop(os_type: str) -> None:
    """Install XFCE desktop environment."""
    print("\n[3/8] Installing XFCE desktop environment...")
    print("  (This may take several minutes)")

    if os_type == "debian":
        run("apt-get install -y -qq xfce4 xfce4-goodies")
    else:
        run("dnf groupinstall -y 'Xfce Desktop'")

    print("  ✓ XFCE desktop installed")


def install_xrdp(username: str, os_type: str) -> None:
    """Install and configure xRDP."""
    print("\n[4/8] Installing xRDP...")
    
    safe_username = shlex.quote(username)

    if os_type == "debian":
        run("apt-get install -y -qq xrdp")
        run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    else:
        run("dnf install -y -q xrdp")

    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    # Configure user session (username already validated, path is safe)
    xsession_path = f"/home/{username}/.xsession"
    with open(xsession_path, "w") as f:
        f.write("xfce4-session\n")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured")


def configure_firewall(os_type: str) -> None:
    """Configure firewall to allow SSH and RDP."""
    print("\n[5/8] Configuring firewall...")

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


def configure_fail2ban(os_type: str) -> None:
    """Install and configure fail2ban for RDP protection."""
    print("\n[6/8] Installing fail2ban for RDP brute-force protection...")

    if os_type == "debian":
        run("apt-get install -y -qq fail2ban")
    else:
        run("dnf install -y -q fail2ban")

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

    with open("/etc/fail2ban/filter.d/xrdp.conf", "w") as f:
        f.write(fail2ban_xrdp_filter)

    with open("/etc/fail2ban/jail.d/xrdp.local", "w") as f:
        f.write(fail2ban_xrdp_jail)

    run("systemctl enable fail2ban")
    run("systemctl restart fail2ban")

    print("  ✓ fail2ban configured (3 failed attempts = 1 hour ban)")


def harden_ssh() -> None:
    """Harden SSH configuration."""
    print("\n[7/8] Hardening SSH configuration...")

    run("cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak")

    ssh_hardening = [
        ("PermitRootLogin", "prohibit-password"),
        ("PasswordAuthentication", "no"),
        ("X11Forwarding", "no"),
        ("MaxAuthTries", "3"),
    ]

    for key, value in ssh_hardening:
        run(f"sed -i 's/^#*{key}.*/{key} {value}/' /etc/ssh/sshd_config")

    run("systemctl reload sshd || systemctl reload ssh", check=False)

    print("  ✓ SSH hardened (key-only auth, no root password, max 3 attempts)")


def configure_auto_updates(os_type: str) -> None:
    """Configure automatic security updates."""
    print("\n[8/8] Configuring automatic security updates...")

    if os_type == "debian":
        run("apt-get install -y -qq unattended-upgrades")

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
        run("sed -i 's/apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf")
        run("sed -i 's/upgrade_type = default/upgrade_type = security/' /etc/dnf/automatic.conf")
        run("systemctl enable dnf-automatic.timer")
        run("systemctl start dnf-automatic.timer")

    print("  ✓ Automatic security updates enabled")


def main() -> int:
    """Main entry point."""
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <username> <password>")
        return 1

    username = sys.argv[1]
    password = sys.argv[2]
    
    # Validate username format for security
    if not validate_username(username):
        print(f"Error: Invalid username format: {username}")
        print("Username must start with a lowercase letter or underscore,")
        print("contain only lowercase letters, numbers, underscores, or hyphens,")
        print("and be 32 characters or less.")
        return 1

    print("=" * 60)
    print("Remote Workstation Setup Script")
    print("=" * 60)

    # Detect OS
    os_type = detect_os()
    print(f"Detected OS type: {os_type}")

    # Run setup steps
    create_user(username, password, os_type)
    configure_time_sync(os_type)
    install_desktop(os_type)
    install_xrdp(username, os_type)
    configure_firewall(os_type)
    configure_fail2ban(os_type)
    harden_ssh()
    configure_auto_updates(os_type)

    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
