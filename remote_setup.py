#!/usr/bin/env python3
"""
Remote Workstation Setup Script

Usage (on the host):
    python3 remote_setup.py                           # Set up current user
    python3 remote_setup.py <username>                # Set up specified user
    python3 remote_setup.py <username> <password>     # Set up user with password
    python3 remote_setup.py <username> <password> <timezone>

Supported OS: Debian/Ubuntu, Fedora
"""

import getpass
import os
import re
import shlex
import subprocess
import sys
from typing import Optional


def validate_username(username: str) -> bool:
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  Running: {cmd[:80]}..." if len(cmd) > 80 else f"  Running: {cmd}")
    sys.stdout.flush()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(f"    Warning: {result.stderr[:200]}")
            sys.stdout.flush()
    return result


def detect_os() -> str:
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
    print("\n[2/13] Configuring UTF-8 locale...")
    sys.stdout.flush()
    
    if os_type == "debian":
        run("apt-get install -y -qq locales")
        run("sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen")
        run("locale-gen")
        run("update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8")
    else:
        run("dnf install -y -q glibc-langpack-en")
    
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
    
    env_content = 'LANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8\n'
    with open("/etc/environment", "a+") as f:
        f.seek(0)
        existing = f.read()
        if "LANG=en_US.UTF-8" not in existing:
            f.write(env_content)
    
    print("  ✓ UTF-8 locale configured (en_US.UTF-8)")
    sys.stdout.flush()


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


def setup_user(username: str, password: Optional[str], os_type: str) -> None:
    print("\n[3/13] Setting up user...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)
    
    result = run(f"id {safe_username}", check=False)
    user_exists = result.returncode == 0
    
    if not user_exists:
        run(f"useradd -m -s /bin/bash {safe_username}")
        print(f"  Created new user: {username}")
        if password:
            if set_user_password(username, password):
                print("  Password set")
    else:
        print(f"  User already exists: {username}")
        if password:
            if set_user_password(username, password):
                print("  Password updated")
        else:
            print("  Password unchanged")
    
    if os_type == "debian":
        run(f"usermod -aG sudo {safe_username}", check=False)
    else:
        run(f"usermod -aG wheel {safe_username}", check=False)
    
    print("  ✓ User configured with sudo privileges")
    sys.stdout.flush()


def configure_time_sync(os_type: str, timezone: Optional[str] = None) -> None:
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

    tz = timezone if timezone else "UTC"
    run(f"timedatectl set-timezone {shlex.quote(tz)}")
    print(f"  ✓ Time synchronization configured (NTP enabled, timezone: {tz})")
    sys.stdout.flush()


def install_desktop(os_type: str) -> None:
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
    print("\n[6/14] Installing xRDP...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)

    if os_type == "debian":
        run("apt-get install -y -qq xrdp")
        run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    else:
        run("dnf install -y -q xrdp")

    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    xsession_path = f"/home/{username}/.xsession"
    with open(xsession_path, "w") as f:
        f.write("xfce4-session\n")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured")
    sys.stdout.flush()


def configure_audio(username: str, os_type: str) -> None:
    print("\n[7/14] Configuring audio for RDP...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)

    if os_type == "debian":
        run("apt-get install -y -qq pulseaudio pulseaudio-utils")
        
        # Install build dependencies for pulseaudio-module-xrdp
        # The module requires PulseAudio source configured to generate internal headers
        run("apt-get install -y -qq build-essential dpkg-dev git autoconf libtool")
        run("apt-get install -y -qq meson")  # Modern PA versions use meson
        
        # Get PulseAudio build dependencies and source
        run("apt-get build-dep -y pulseaudio")
        
        # Download and configure PulseAudio source to generate required headers
        pulse_src_dir = "/tmp/pulseaudio-src"
        run(f"rm -rf {pulse_src_dir}")
        run(f"mkdir -p {pulse_src_dir}")
        
        # Use apt-get source to get matching PA version
        run(f"cd {pulse_src_dir} && apt-get source pulseaudio")
        
        # Find the extracted source directory
        result = run(f"find {pulse_src_dir} -maxdepth 1 -type d -name 'pulseaudio-*' | head -1")
        pa_build_dir = result.stdout.strip() if result.stdout else ""
        
        if pa_build_dir:
            # Configure PA source to generate config.h and internal headers
            # Check if meson or autotools
            if os.path.exists(f"{pa_build_dir}/meson.build"):
                run(f"cd {pa_build_dir} && meson setup build", check=False)
            elif os.path.exists(f"{pa_build_dir}/configure"):
                run(f"cd {pa_build_dir} && ./configure", check=False)
            
            # Clone and build pulseaudio-module-xrdp
            module_dir = "/tmp/pulseaudio-module-xrdp"
            run(f"rm -rf {module_dir}")
            run(f"git clone https://github.com/neutrinolabs/pulseaudio-module-xrdp.git {module_dir}")
            
            run(f"cd {module_dir} && ./bootstrap")
            run(f"cd {module_dir} && ./configure PULSE_DIR={pa_build_dir}")
            run(f"cd {module_dir} && make")
            run(f"cd {module_dir} && make install")
            
            # Verify installation
            result = run("ls $(pkg-config --variable=modlibexecdir libpulse) 2>/dev/null | grep xrdp", check=False)
            if "xrdp" in (result.stdout or ""):
                print("  Module installed successfully")
            else:
                print("  Warning: Module installation may have failed, check logs")
        else:
            print("  Warning: Could not find PulseAudio source directory")
    else:
        run("dnf install -y -q pulseaudio pulseaudio-utils")
        run("dnf install -y -q pulseaudio-module-xrdp", check=False)
    
    run(f"usermod -aG audio {safe_username}", check=False)
    
    home_dir = f"/home/{username}"
    pulse_dir = f"{home_dir}/.config/pulse"
    os.makedirs(pulse_dir, exist_ok=True)
    
    client_conf = f"{pulse_dir}/client.conf"
    with open(client_conf, "w") as f:
        f.write("autospawn = yes\n")
        f.write("daemon-binary = /usr/bin/pulseaudio\n")
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(pulse_dir)}")
    
    run("systemctl restart xrdp", check=False)
    
    print("  ✓ Audio configured (PulseAudio + xRDP module)")
    sys.stdout.flush()


def configure_firewall(os_type: str) -> None:
    print("\n[8/14] Configuring firewall...")
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
    print("\n[9/14] Installing fail2ban for RDP brute-force protection...")
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
    print("\n[10/14] Hardening SSH configuration...")
    sys.stdout.flush()

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
    print("\n[11/14] Configuring automatic security updates...")
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
    print("\n[12/14] Installing CLI tools...")
    sys.stdout.flush()

    if os_type == "debian":
        run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils")
    else:
        run("dnf install -y -q neovim btop htop curl wget git tmux unzip xdg-utils")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip)")
    sys.stdout.flush()


def install_desktop_apps(os_type: str, username: str) -> None:
    print("\n[13/14] Installing desktop applications...")
    sys.stdout.flush()

    print("  Installing LibreOffice...")
    sys.stdout.flush()
    if os_type == "debian":
        run("apt-get install -y -qq libreoffice")
    else:
        run("dnf install -y -q libreoffice")

    print("  Installing Brave browser...")
    sys.stdout.flush()
    if os_type == "debian":
        run("apt-get install -y -qq curl gnupg")
        run("curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg", check=False)
        run('echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" > /etc/apt/sources.list.d/brave-browser-release.list', check=False)
        run("apt-get update -qq", check=False)
        run("apt-get install -y -qq brave-browser", check=False)
    else:
        run("dnf config-manager --add-repo https://brave-browser-rpm-release.s3.brave.com/brave-browser.repo", check=False)
        run("rpm --import https://brave-browser-rpm-release.s3.brave.com/brave-core.asc", check=False)
        run("dnf install -y -q brave-browser", check=False)

    print("  Installing VSCodium...")
    sys.stdout.flush()
    if os_type == "debian":
        run("wget -qO - https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/raw/master/pub.gpg | gpg --dearmor | dd of=/usr/share/keyrings/vscodium-archive-keyring.gpg 2>/dev/null", check=False)
        run('echo "deb [signed-by=/usr/share/keyrings/vscodium-archive-keyring.gpg] https://download.vscodium.com/debs vscodium main" > /etc/apt/sources.list.d/vscodium.list', check=False)
        run("apt-get update -qq", check=False)
        run("apt-get install -y -qq codium", check=False)
    else:
        run('printf "[gitlab.com_paulcarroty_vscodium_repo]\\nname=download.vscodium.com\\nbaseurl=https://download.vscodium.com/rpms/\\nenabled=1\\ngpgcheck=1\\nrepo_gpgcheck=1\\ngpgkey=https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/-/raw/master/pub.gpg\\nmetadata_expire=1h\\n" > /etc/yum.repos.d/vscodium.repo', check=False)
        run("dnf install -y -q codium", check=False)

    print("  Installing Discord...")
    sys.stdout.flush()
    if os_type == "debian":
        run("wget -qO /tmp/discord.deb 'https://discord.com/api/download?platform=linux&format=deb'", check=False)
        run("apt-get install -y -qq /tmp/discord.deb", check=False)
        run("rm -f /tmp/discord.deb", check=False)
    else:
        print("    Note: Discord not easily available for Fedora via packages")

    print("  ✓ Desktop apps installed (LibreOffice, Brave, VSCodium, Discord)")
    sys.stdout.flush()


def configure_default_browser(username: str) -> None:
    print("\n[14/14] Configuring default browser...")
    sys.stdout.flush()
    
    safe_username = shlex.quote(username)
    
    user_apps_dir = f"/home/{username}/.local/share/applications"
    os.makedirs(user_apps_dir, exist_ok=True)
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.local")
    
    mimeapps_path = f"/home/{username}/.config/mimeapps.list"
    os.makedirs(f"/home/{username}/.config", exist_ok=True)
    
    mimeapps_content = """[Default Applications]
x-scheme-handler/http=brave-browser.desktop
x-scheme-handler/https=brave-browser.desktop
text/html=brave-browser.desktop
application/xhtml+xml=brave-browser.desktop
"""
    
    with open(mimeapps_path, "w") as f:
        f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.config")
    
    run("xdg-mime default brave-browser.desktop x-scheme-handler/http", check=False)
    run("xdg-mime default brave-browser.desktop x-scheme-handler/https", check=False)
    
    print("  ✓ Default browser set to Brave")
    sys.stdout.flush()


def main() -> int:
    timezone = None
    password = None
    
    if len(sys.argv) == 1:
        username = getpass.getuser()
        print(f"No username specified, using current user: {username}")
    elif len(sys.argv) == 2:
        username = sys.argv[1]
    elif len(sys.argv) == 3:
        username = sys.argv[1]
        password = sys.argv[2] if sys.argv[2] else None
    elif len(sys.argv) == 4:
        username = sys.argv[1]
        password = sys.argv[2] if sys.argv[2] else None
        timezone = sys.argv[3] if sys.argv[3] else None
    else:
        print(f"Usage: {sys.argv[0]} [username] [password] [timezone]")
        return 1
    
    if not validate_username(username):
        print(f"Error: Invalid username format: {username}")
        return 1

    print("=" * 60)
    print("Remote Workstation Setup Script")
    print("=" * 60)
    print(f"Target user: {username}")
    if timezone:
        print(f"Timezone: {timezone}")
    else:
        print("Timezone: UTC (default)")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"Detected OS type: {os_type}")
    sys.stdout.flush()

    ensure_sudo_installed(os_type)
    configure_locale(os_type)
    setup_user(username, password, os_type)
    configure_time_sync(os_type, timezone)
    install_desktop(os_type)
    install_xrdp(username, os_type)
    configure_audio(username, os_type)
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
