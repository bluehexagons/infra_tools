#!/usr/bin/env python3
"""
Remote Workstation Setup Script

This script sets up a Linux workstation with:
- XFCE desktop environment
- xRDP server for RDP access
- Secure defaults (firewall, SSH hardening, fail2ban for RDP)
- NTP time synchronization
- Automatic security updates
- CLI tools (neovim, btop, htop, etc.)
- Desktop applications via Flatpak (LibreOffice, Brave, VSCodium, Discord)
- UTF-8 locale configuration
- Default browser set to Brave

Usage (on the host):
    # Set up current user (no new user creation)
    python3 remote_setup.py
    
    # Set up with a specific username (creates user if needed)
    python3 remote_setup.py <username>
    
    # Set up with username and password (creates user with password)
    python3 remote_setup.py <username> <password>
    
    # Set up with username, password, and timezone
    python3 remote_setup.py <username> <password> <timezone>

Supported OS: Debian/Ubuntu, Fedora

This script is idempotent and safe to run multiple times.

Note: Flatpak apps may not work in unprivileged containers (e.g., Proxmox LXC)
due to user namespace restrictions. Enable nesting or use a privileged container.
"""

import getpass
import os
import re
import shlex
import subprocess
import sys
from typing import Optional


def validate_username(username: str) -> bool:
    """Validate username format (lowercase letters, numbers, underscore, hyphen)."""
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    print(f"  Running: {cmd[:80]}..." if len(cmd) > 80 else f"  Running: {cmd}")
    sys.stdout.flush()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(f"    Warning: {result.stderr[:200]}")
            sys.stdout.flush()
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


def ensure_sudo_installed(os_type: str) -> None:
    """Ensure sudo is installed (for minimal distros)."""
    print("\n[1/13] Ensuring sudo is installed...")
    sys.stdout.flush()
    
    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get update -qq")
        run("apt-get install -y -qq sudo")
    else:
        run("dnf install -y -q sudo")
    
    print("  ✓ sudo is available")
    sys.stdout.flush()


def configure_locale(os_type: str) -> None:
    """Configure UTF-8 locale for proper terminal support."""
    print("\n[2/13] Configuring UTF-8 locale...")
    sys.stdout.flush()
    
    if os_type == "debian":
        # Install locales package and generate en_US.UTF-8
        run("apt-get install -y -qq locales")
        run("sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen")
        run("locale-gen")
        run("update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8")
    else:
        # Fedora usually has locales, but ensure glibc-langpack-en is installed
        run("dnf install -y -q glibc-langpack-en")
    
    # Set environment variables for current session
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
    
    # Add to /etc/environment for persistence
    env_content = 'LANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8\n'
    with open("/etc/environment", "a+") as f:
        f.seek(0)
        existing = f.read()
        if "LANG=en_US.UTF-8" not in existing:
            f.write(env_content)
    
    print("  ✓ UTF-8 locale configured (en_US.UTF-8)")
    sys.stdout.flush()


def setup_user(username: str, password: Optional[str], os_type: str) -> None:
    """Set up user with sudo privileges (creates if doesn't exist)."""
    print("\n[3/13] Setting up user...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)
    
    # Check if user exists
    result = run(f"id {safe_username}", check=False)
    user_exists = result.returncode == 0
    
    if not user_exists:
        run(f"useradd -m -s /bin/bash {safe_username}")
        print(f"  Created new user: {username}")
    else:
        print(f"  User already exists: {username}")
    
    # Set password if provided
    if password:
        process = subprocess.run(
            ["chpasswd"],
            input=f"{username}:{password}\n",
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print(f"  Warning: Failed to set password: {process.stderr}")
        else:
            print("  Password updated")
    
    # Ensure user is in sudo/wheel group
    if os_type == "debian":
        run(f"usermod -aG sudo {safe_username}", check=False)
    else:
        run(f"usermod -aG wheel {safe_username}", check=False)
    
    print("  ✓ User configured with sudo privileges")
    sys.stdout.flush()


def configure_time_sync(os_type: str, timezone: Optional[str] = None) -> None:
    """Configure NTP time synchronization."""
    print("\n[4/13] Configuring time synchronization...")
    sys.stdout.flush()

    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get install -y -qq systemd-timesyncd")
        run("timedatectl set-ntp true")
    else:
        run("dnf install -y -q chrony")
        run("systemctl enable chronyd")
        run("systemctl start chronyd")

    # Set timezone (use provided timezone or default to UTC)
    tz = timezone if timezone else "UTC"
    run(f"timedatectl set-timezone {shlex.quote(tz)}")
    print(f"  ✓ Time synchronization configured (NTP enabled, timezone: {tz})")
    sys.stdout.flush()


def install_desktop(os_type: str) -> None:
    """Install XFCE desktop environment."""
    print("\n[5/13] Installing XFCE desktop environment...")
    print("  (This may take several minutes)")
    sys.stdout.flush()

    if os_type == "debian":
        run("apt-get install -y -qq xfce4 xfce4-goodies")
    else:
        run("dnf groupinstall -y 'Xfce Desktop'")

    print("  ✓ XFCE desktop installed")
    sys.stdout.flush()


def install_xrdp(username: str, os_type: str) -> None:
    """Install and configure xRDP."""
    print("\n[6/13] Installing xRDP...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)

    if os_type == "debian":
        run("apt-get install -y -qq xrdp")
        run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    else:
        run("dnf install -y -q xrdp")

    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    # Configure user session (create/update .xsession)
    xsession_path = f"/home/{username}/.xsession"
    with open(xsession_path, "w") as f:
        f.write("xfce4-session\n")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured")
    sys.stdout.flush()


def configure_firewall(os_type: str) -> None:
    """Configure firewall to allow SSH and RDP."""
    print("\n[7/13] Configuring firewall...")
    sys.stdout.flush()

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
    sys.stdout.flush()


def configure_fail2ban(os_type: str) -> None:
    """Install and configure fail2ban for RDP protection."""
    print("\n[8/13] Installing fail2ban for RDP brute-force protection...")
    sys.stdout.flush()

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

    # Create directories if they don't exist
    os.makedirs("/etc/fail2ban/filter.d", exist_ok=True)
    os.makedirs("/etc/fail2ban/jail.d", exist_ok=True)

    with open("/etc/fail2ban/filter.d/xrdp.conf", "w") as f:
        f.write(fail2ban_xrdp_filter)

    with open("/etc/fail2ban/jail.d/xrdp.local", "w") as f:
        f.write(fail2ban_xrdp_jail)

    run("systemctl enable fail2ban")
    run("systemctl restart fail2ban")

    print("  ✓ fail2ban configured (3 failed attempts = 1 hour ban)")
    sys.stdout.flush()


def harden_ssh() -> None:
    """Harden SSH configuration."""
    print("\n[9/13] Hardening SSH configuration...")
    sys.stdout.flush()

    # Only backup if backup doesn't exist (idempotent)
    if not os.path.exists("/etc/ssh/sshd_config.bak"):
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
    sys.stdout.flush()


def configure_auto_updates(os_type: str) -> None:
    """Configure automatic security updates."""
    print("\n[10/13] Configuring automatic security updates...")
    sys.stdout.flush()

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
    sys.stdout.flush()


def install_cli_tools(os_type: str) -> None:
    """Install useful CLI tools for development and system monitoring."""
    print("\n[11/13] Installing CLI tools...")
    sys.stdout.flush()

    # Common CLI tools useful for Proxmox containers and development
    if os_type == "debian":
        run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils")
    else:
        run("dnf install -y -q neovim btop htop curl wget git tmux unzip xdg-utils")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip)")
    sys.stdout.flush()


def install_desktop_apps(os_type: str, username: str) -> None:
    """Install desktop applications via Flatpak."""
    print("\n[12/13] Installing desktop applications via Flatpak...")
    sys.stdout.flush()

    # Install Flatpak
    if os_type == "debian":
        run("apt-get install -y -qq flatpak")
    else:
        run("dnf install -y -q flatpak")

    # Add Flathub repository (--if-not-exists makes it idempotent)
    run("flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo")

    # Install desktop applications (flatpak install is idempotent)
    # Note: These may fail in unprivileged containers due to user namespace restrictions
    run("flatpak install -y flathub org.libreoffice.LibreOffice", check=False)
    run("flatpak install -y flathub com.brave.Browser", check=False)
    run("flatpak install -y flathub com.vscodium.codium", check=False)
    run("flatpak install -y flathub com.discordapp.Discord", check=False)

    print("  ✓ Desktop apps installed (LibreOffice, Brave, VSCodium, Discord)")
    print("  Note: Flatpak apps may not work in unprivileged containers")
    sys.stdout.flush()


def configure_default_browser(username: str) -> None:
    """Set Brave as the default web browser."""
    print("\n[13/13] Configuring default browser...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)
    
    # Create .local/share/applications directory for the user
    user_apps_dir = f"/home/{username}/.local/share/applications"
    os.makedirs(user_apps_dir, exist_ok=True)
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.local")
    
    # Create mimeapps.list to set default browser
    mimeapps_path = f"/home/{username}/.config/mimeapps.list"
    os.makedirs(f"/home/{username}/.config", exist_ok=True)
    
    mimeapps_content = """[Default Applications]
x-scheme-handler/http=com.brave.Browser.desktop
x-scheme-handler/https=com.brave.Browser.desktop
text/html=com.brave.Browser.desktop
application/xhtml+xml=com.brave.Browser.desktop
"""
    
    with open(mimeapps_path, "w") as f:
        f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.config")
    
    # Also try to set it system-wide as fallback
    run("xdg-mime default com.brave.Browser.desktop x-scheme-handler/http", check=False)
    run("xdg-mime default com.brave.Browser.desktop x-scheme-handler/https", check=False)
    
    print("  ✓ Default browser set to Brave")
    sys.stdout.flush()


def main() -> int:
    """Main entry point."""
    # Parse arguments: username password timezone
    # When called from setup_workstation_desktop.py, all three args are always passed
    # Empty string for password means "don't change password"
    # Empty string for timezone means "use UTC"
    # When run directly, fewer arguments are accepted for convenience
    
    timezone = None
    password = None
    
    if len(sys.argv) == 1:
        # No arguments - use current user
        username = getpass.getuser()
        print(f"No username specified, using current user: {username}")
    elif len(sys.argv) == 2:
        # One argument - username only
        username = sys.argv[1]
    elif len(sys.argv) == 3:
        # Two arguments - username and password
        username = sys.argv[1]
        password = sys.argv[2] if sys.argv[2] else None  # Empty string = no password change
    elif len(sys.argv) == 4:
        # Three arguments - username, password, and timezone
        username = sys.argv[1]
        password = sys.argv[2] if sys.argv[2] else None  # Empty string = no password change
        timezone = sys.argv[3] if sys.argv[3] else None  # Empty string = use UTC
    else:
        print(f"Usage: {sys.argv[0]} [username] [password] [timezone]")
        print("  No args: set up current user")
        print("  1 arg:   set up specified user (no password change)")
        print("  2 args:  set up user with password (empty string = no change)")
        print("  3 args:  set up user with password and timezone")
        return 1
    
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
    print(f"Target user: {username}")
    if timezone:
        print(f"Timezone: {timezone}")
    else:
        print("Timezone: UTC (default)")
    print("This script is idempotent - safe to run multiple times.")
    sys.stdout.flush()

    # Detect OS
    os_type = detect_os()
    print(f"Detected OS type: {os_type}")
    sys.stdout.flush()

    # Run setup steps
    ensure_sudo_installed(os_type)
    configure_locale(os_type)
    setup_user(username, password, os_type)
    configure_time_sync(os_type, timezone)
    install_desktop(os_type)
    install_xrdp(username, os_type)
    configure_firewall(os_type)
    configure_fail2ban(os_type)
    harden_ssh()
    configure_auto_updates(os_type)
    install_cli_tools(os_type)
    install_desktop_apps(os_type, username)
    configure_default_browser(username)

    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
