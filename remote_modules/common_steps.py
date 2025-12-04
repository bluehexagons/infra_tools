"""Common setup steps for all system types."""

import os
import shlex
import subprocess
from typing import Optional

from .utils import run, is_package_installed, is_service_active, file_contains, generate_password


def set_user_password(username: str, password: str) -> bool:
    process = subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        capture_output=True
    )
    if process.returncode != 0:
        print(f"  Warning: Failed to set password: {process.stderr}")
        return False
    return True


def update_and_upgrade_packages(os_type: str, **_) -> None:
    print("  Updating package lists...")
    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get update -qq")
        print("  Upgrading packages...")
        run("apt-get upgrade -y -qq")
        run("apt-get autoremove -y -qq")
    else:
        run("dnf upgrade -y -q")
        run("dnf autoremove -y -q")
    
    print("  ✓ System packages updated and upgraded")


def ensure_sudo_installed(os_type: str, **_) -> None:
    if is_package_installed("sudo", os_type):
        print("  ✓ sudo already installed")
        return
    
    if os_type == "debian":
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get update -qq")
        run("apt-get install -y -qq sudo")
    else:
        run("dnf install -y -q sudo")
    
    print("  ✓ sudo installed")


def configure_locale(os_type: str, **_) -> None:
    if file_contains("/etc/environment", "LANG=en_US.UTF-8"):
        print("  ✓ UTF-8 locale already configured")
        return
    
    if os_type == "debian":
        run("apt-get install -y -qq locales")
        run("sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen")
        run("locale-gen")
        run("update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8")
    else:
        run("dnf install -y -q glibc-langpack-en")
    
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
    
    with open("/etc/environment", "a+") as f:
        f.seek(0)
        existing = f.read()
        if "LANG=en_US.UTF-8" not in existing:
            f.write('LANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8\n')
    
    print("  ✓ UTF-8 locale configured (en_US.UTF-8)")


def setup_user(username: str, pw: Optional[str], os_type: str, **_) -> None:
    """Set up user account."""
    safe_username = shlex.quote(username)
    
    result = run(f"id {safe_username}", check=False)
    user_exists = result.returncode == 0
    
    if not user_exists:
        run(f"useradd -m -s /bin/bash {safe_username}")
        print(f"  Created new user: {username}")
        if pw:
            if set_user_password(username, pw):
                print("  Password set")
        else:
            generated = generate_password()
            if set_user_password(username, generated):
                print(f"  Generated password: {generated}")
    else:
        print(f"  User already exists: {username}")
        if pw:
            if set_user_password(username, pw):
                print("  Password updated")
    
    if os_type == "debian":
        run(f"usermod -aG sudo {safe_username}", check=False)
    else:
        run(f"usermod -aG wheel {safe_username}", check=False)
    
    result = run("getent group remoteusers", check=False)
    if result.returncode == 0:
        run(f"usermod -aG remoteusers {safe_username}", check=False)
        print("  ✓ User configured with sudo privileges and remoteusers group")
    else:
        print("  ✓ User configured with sudo privileges")


def generate_ssh_key(username: str, **_) -> None:
    """Generate SSH key pair for user using default algorithm."""
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
    ssh_dir = f"{user_home}/.ssh"
    private_key = f"{ssh_dir}/id_ed25519"
    public_key = f"{private_key}.pub"
    
    # Check if user already has SSH key
    if os.path.exists(private_key):
        print(f"  ✓ SSH key already exists for {username}")
        return
    
    # Create .ssh directory if it doesn't exist
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    
    # Generate SSH key with default algorithm (ed25519)
    # Build the command safely with proper escaping
    safe_private_key = shlex.quote(private_key)
    safe_comment = shlex.quote(f"{username}@workstation")
    run(f"su - {safe_username} -c 'ssh-keygen -t ed25519 -f {safe_private_key} -N \"\" -C {safe_comment}'")
    
    # Set proper permissions
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(private_key)}")
    run(f"chmod 644 {shlex.quote(public_key)}", check=False)
    
    print(f"  ✓ SSH key generated for {username} (~/.ssh/id_ed25519)")


def copy_ssh_keys_to_user(username: str, **_) -> None:
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
    ssh_dir = f"{user_home}/.ssh"
    authorized_keys = f"{ssh_dir}/authorized_keys"
    
    # Check if root has authorized_keys
    if not os.path.exists("/root/.ssh/authorized_keys"):
        print("  ℹ No SSH keys found in /root/.ssh/authorized_keys to copy")
        return
    
    # Create .ssh directory for user if it doesn't exist
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    
    # Copy root's authorized_keys to user
    run(f"cp /root/.ssh/authorized_keys {shlex.quote(authorized_keys)}")
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(authorized_keys)}")
    
    print(f"  ✓ SSH keys copied to {username}")


def configure_time_sync(os_type: str, timezone: Optional[str] = None, **_) -> None:
    tz = timezone if timezone else "UTC"
    
    if os_type == "debian":
        if not is_package_installed("systemd-timesyncd", os_type):
            os.environ["DEBIAN_FRONTEND"] = "noninteractive"
            run("apt-get install -y -qq systemd-timesyncd")
        run("timedatectl set-ntp true")
    else:
        if not is_package_installed("chrony", os_type):
            run("dnf install -y -q chrony")
        if not is_service_active("chronyd"):
            run("systemctl enable chronyd")
            run("systemctl start chronyd")

    run(f"timedatectl set-timezone {shlex.quote(tz)}")
    print(f"  ✓ Time synchronization configured (NTP enabled, timezone: {tz})")


def install_cli_tools(os_type: str, **_) -> None:
    if is_package_installed("neovim", os_type):
        print("  ✓ CLI tools already installed")
        return

    if os_type == "debian":
        run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils")
    else:
        run("dnf install -y -q neovim btop htop curl wget git tmux unzip xdg-utils")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip)")


def check_restart_required(os_type: str, **_) -> None:
    needs_restart = False
    
    if os_type == "debian":
        # Check for /var/run/reboot-required
        if os.path.exists("/var/run/reboot-required"):
            needs_restart = True
    else:
        # For Fedora/RHEL, check if kernel was updated
        result = run("needs-restarting -r", check=False)
        if result.returncode != 0:
            needs_restart = True
    
    if needs_restart:
        print("  ⚠ System restart recommended (kernel/system updates)")
        print("  Run 'sudo reboot' when convenient")
    else:
        print("  ✓ No restart required")
