"""Setup step functions for remote workstation configuration."""

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
    
    print("  ✓ User configured with sudo privileges")


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


def install_desktop(os_type: str, **_) -> None:
    if os_type == "debian":
        if is_package_installed("xfce4", os_type):
            print("  ✓ XFCE desktop already installed")
            return
        run("apt-get install -y -qq xfce4 xfce4-goodies")
    else:
        if is_package_installed("xfce4-session", os_type):
            print("  ✓ XFCE desktop already installed")
            return
        run("dnf groupinstall -y 'Xfce Desktop'")

    print("  ✓ XFCE desktop installed")


def install_xrdp(username: str, os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    xsession_path = f"/home/{username}/.xsession"
    
    if is_package_installed("xrdp", os_type) and os.path.exists(xsession_path):
        if is_service_active("xrdp"):
            print("  ✓ xRDP already installed and configured")
            return

    if os_type == "debian":
        if not is_package_installed("xrdp", os_type):
            run("apt-get install -y -qq xrdp")
        run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    else:
        if not is_package_installed("xrdp", os_type):
            run("dnf install -y -q xrdp")

    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    with open(xsession_path, "w") as f:
        f.write("xfce4-session\n")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured")


def configure_audio(username: str, os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    home_dir = f"/home/{username}"
    pulse_dir = f"{home_dir}/.config/pulse"
    client_conf = f"{pulse_dir}/client.conf"
    
    if os.path.exists(client_conf) and is_package_installed("pulseaudio", os_type):
        print("  ✓ Audio already configured")
        return

    if os_type == "debian":
        run("apt-get install -y -qq pulseaudio pulseaudio-utils")
        run("apt-get install -y -qq build-essential dpkg-dev libpulse-dev git autoconf libtool", check=False)
        
        module_dir = "/tmp/pulseaudio-module-xrdp"
        if not os.path.exists(module_dir):
            run(f"git clone https://github.com/neutrinolabs/pulseaudio-module-xrdp.git {module_dir}", check=False)
        
        run(f"cd {module_dir} && ./bootstrap", check=False)
        run(f"cd {module_dir} && ./configure PULSE_DIR=/usr/include/pulse", check=False)
        run(f"cd {module_dir} && make", check=False)
        run(f"cd {module_dir} && make install", check=False)
    else:
        run("dnf install -y -q pulseaudio pulseaudio-utils")
        run("dnf install -y -q pulseaudio-module-xrdp", check=False)
    
    run(f"usermod -aG audio {safe_username}", check=False)
    
    os.makedirs(pulse_dir, exist_ok=True)
    
    with open(client_conf, "w") as f:
        f.write("autospawn = yes\n")
        f.write("daemon-binary = /usr/bin/pulseaudio\n")
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(pulse_dir)}")
    run("systemctl restart xrdp", check=False)
    
    print("  ✓ Audio configured (PulseAudio + xRDP module)")


def configure_firewall(os_type: str, **_) -> None:
    if os_type == "debian":
        result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
        if result.returncode == 0:
            print("  ✓ Firewall already configured")
            return
        
        run("apt-get install -y -qq ufw")
        run("ufw default deny incoming")
        run("ufw default allow outgoing")
        run("ufw allow ssh")
        run("ufw allow 3389/tcp")
        run("ufw --force enable")
    else:
        if is_service_active("firewalld"):
            result = run("firewall-cmd --query-port=3389/tcp", check=False)
            if result.returncode == 0:
                print("  ✓ Firewall already configured")
                return
        
        run("systemctl enable firewalld", check=False)
        run("systemctl start firewalld", check=False)
        run("firewall-cmd --permanent --add-service=ssh", check=False)
        run("firewall-cmd --permanent --add-port=3389/tcp", check=False)
        run("firewall-cmd --reload", check=False)

    print("  ✓ Firewall configured (SSH and RDP allowed)")


def configure_fail2ban(os_type: str, **_) -> None:
    if os.path.exists("/etc/fail2ban/jail.d/xrdp.local"):
        if is_service_active("fail2ban"):
            print("  ✓ fail2ban already configured")
            return

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


def harden_ssh(**_) -> None:
    sshd_config = "/etc/ssh/sshd_config"
    
    if file_contains(sshd_config, "PasswordAuthentication no"):
        if file_contains(sshd_config, "MaxAuthTries 3"):
            print("  ✓ SSH already hardened")
            return

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


def configure_auto_updates(os_type: str, **_) -> None:
    if os_type == "debian":
        if os.path.exists("/etc/apt/apt.conf.d/20auto-upgrades"):
            if is_service_active("unattended-upgrades"):
                print("  ✓ Automatic updates already configured")
                return
        
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
        if is_service_active("dnf-automatic.timer"):
            print("  ✓ Automatic updates already configured")
            return
        
        run("dnf install -y -q dnf-automatic")
        run("sed -i 's/apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf")
        run("sed -i 's/upgrade_type = default/upgrade_type = security/' /etc/dnf/automatic.conf")
        run("systemctl enable dnf-automatic.timer")
        run("systemctl start dnf-automatic.timer")

    print("  ✓ Automatic security updates enabled")


def install_cli_tools(os_type: str, **_) -> None:
    if is_package_installed("neovim", os_type):
        print("  ✓ CLI tools already installed")
        return

    if os_type == "debian":
        run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils")
    else:
        run("dnf install -y -q neovim btop htop curl wget git tmux unzip xdg-utils")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip)")


def install_desktop_apps(os_type: str, username: str, **_) -> None:
    all_installed = (
        is_package_installed("libreoffice", os_type) and
        is_package_installed("brave-browser", os_type) and
        is_package_installed("codium", os_type)
    )
    if all_installed:
        print("  ✓ Desktop apps already installed")
        return

    if not is_package_installed("libreoffice", os_type):
        print("  Installing LibreOffice...")
        if os_type == "debian":
            run("apt-get install -y -qq libreoffice")
        else:
            run("dnf install -y -q libreoffice")
    else:
        print("  ✓ LibreOffice already installed")

    print("  Installing Brave browser...")
    if os_type == "debian":
        if not os.path.exists("/usr/share/keyrings/brave-browser-archive-keyring.gpg"):
            run("apt-get install -y -qq curl gnupg")
            run("curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg", check=False)
            run('echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" > /etc/apt/sources.list.d/brave-browser-release.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("brave-browser", os_type):
            run("apt-get install -y -qq brave-browser", check=False)
    else:
        if not is_package_installed("brave-browser", os_type):
            run("dnf config-manager --add-repo https://brave-browser-rpm-release.s3.brave.com/brave-browser.repo", check=False)
            run("rpm --import https://brave-browser-rpm-release.s3.brave.com/brave-core.asc", check=False)
            run("dnf install -y -q brave-browser", check=False)

    print("  Installing VSCodium...")
    if os_type == "debian":
        if not os.path.exists("/usr/share/keyrings/vscodium-archive-keyring.gpg"):
            run("wget -qO - https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/raw/master/pub.gpg | gpg --dearmor | dd of=/usr/share/keyrings/vscodium-archive-keyring.gpg 2>/dev/null", check=False)
            run('echo "deb [signed-by=/usr/share/keyrings/vscodium-archive-keyring.gpg] https://download.vscodium.com/debs vscodium main" > /etc/apt/sources.list.d/vscodium.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("codium", os_type):
            run("apt-get install -y -qq codium", check=False)
    else:
        if not is_package_installed("codium", os_type):
            run('printf "[gitlab.com_paulcarroty_vscodium_repo]\\nname=download.vscodium.com\\nbaseurl=https://download.vscodium.com/rpms/\\nenabled=1\\ngpgcheck=1\\nrepo_gpgcheck=1\\ngpgkey=https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/-/raw/master/pub.gpg\\nmetadata_expire=1h\\n" > /etc/yum.repos.d/vscodium.repo', check=False)
            run("dnf install -y -q codium", check=False)

    print("  Installing Discord...")
    if os_type == "debian":
        if not is_package_installed("discord", os_type):
            run("wget -qO /tmp/discord.deb 'https://discord.com/api/download?platform=linux&format=deb'", check=False)
            run("apt-get install -y -qq /tmp/discord.deb", check=False)
            run("rm -f /tmp/discord.deb", check=False)
    else:
        print("    Note: Discord not easily available for Fedora via packages")

    print("  ✓ Desktop apps installed (LibreOffice, Brave, VSCodium, Discord)")


def configure_default_browser(username: str, **_) -> None:
    safe_username = shlex.quote(username)
    mimeapps_path = f"/home/{username}/.config/mimeapps.list"
    
    if os.path.exists(mimeapps_path):
        if file_contains(mimeapps_path, "brave-browser.desktop"):
            print("  ✓ Default browser already set")
            return
    
    user_apps_dir = f"/home/{username}/.local/share/applications"
    os.makedirs(user_apps_dir, exist_ok=True)
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.local")
    
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


def install_workstation_dev_apps(os_type: str, username: str, **_) -> None:
    all_installed = (
        is_package_installed("vivaldi-stable", os_type) and
        (is_package_installed("code", os_type) or os.path.exists("/usr/bin/code"))
    )
    if all_installed:
        print("  ✓ Workstation dev apps already installed")
        return

    print("  Installing Vivaldi browser...")
    if os_type == "debian":
        if not os.path.exists("/usr/share/keyrings/vivaldi-archive-keyring.gpg"):
            run("apt-get install -y -qq curl gnupg")
            run("curl -fsSL https://repo.vivaldi.com/archive/linux_signing_key.pub | gpg --dearmor --output /usr/share/keyrings/vivaldi-archive-keyring.gpg", check=False)
            run('echo "deb [signed-by=/usr/share/keyrings/vivaldi-archive-keyring.gpg] https://repo.vivaldi.com/archive/deb/ stable main" > /etc/apt/sources.list.d/vivaldi.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("vivaldi-stable", os_type):
            run("apt-get install -y -qq vivaldi-stable", check=False)
    else:
        if not is_package_installed("vivaldi-stable", os_type):
            run("dnf config-manager --add-repo https://repo.vivaldi.com/archive/vivaldi-fedora.repo", check=False)
            run("dnf install -y -q vivaldi-stable", check=False)

    print("  Installing Visual Studio Code...")
    if os_type == "debian":
        if not os.path.exists("/etc/apt/trusted.gpg.d/microsoft.gpg"):
            run("apt-get install -y -qq wget gpg")
            run("wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --output /etc/apt/trusted.gpg.d/microsoft.gpg", check=False)
            run('echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("code", os_type):
            run("apt-get install -y -qq code", check=False)
    else:
        if not is_package_installed("code", os_type):
            run("rpm --import https://packages.microsoft.com/keys/microsoft.asc", check=False)
            vscode_repo = """[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
"""
            with open("/etc/yum.repos.d/vscode.repo", "w") as f:
                f.write(vscode_repo)
            run("dnf install -y -q code", check=False)

    print("  ✓ Workstation dev apps installed (Vivaldi, VS Code)")


def configure_vivaldi_browser(username: str, **_) -> None:
    safe_username = shlex.quote(username)
    mimeapps_path = f"/home/{username}/.config/mimeapps.list"
    
    if os.path.exists(mimeapps_path):
        if file_contains(mimeapps_path, "vivaldi-stable.desktop"):
            print("  ✓ Default browser already set")
            return
    
    user_apps_dir = f"/home/{username}/.local/share/applications"
    os.makedirs(user_apps_dir, exist_ok=True)
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.local")
    
    os.makedirs(f"/home/{username}/.config", exist_ok=True)
    
    mimeapps_content = """[Default Applications]
x-scheme-handler/http=vivaldi-stable.desktop
x-scheme-handler/https=vivaldi-stable.desktop
text/html=vivaldi-stable.desktop
application/xhtml+xml=vivaldi-stable.desktop
"""
    
    with open(mimeapps_path, "w") as f:
        f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} /home/{username}/.config")
    
    run("xdg-mime default vivaldi-stable.desktop x-scheme-handler/http", check=False)
    run("xdg-mime default vivaldi-stable.desktop x-scheme-handler/https", check=False)
    
    print("  ✓ Default browser set to Vivaldi")


# Common steps for all system types
COMMON_STEPS = [
    ("Ensuring sudo is installed", ensure_sudo_installed),
    ("Configuring UTF-8 locale", configure_locale),
    ("Setting up user", setup_user),
    ("Configuring time synchronization", configure_time_sync),
]

# Desktop-specific steps
DESKTOP_STEPS = [
    ("Installing XFCE desktop environment", install_desktop),
    ("Installing xRDP", install_xrdp),
    ("Configuring audio for RDP", configure_audio),
]

# Desktop security steps (fail2ban for RDP)
DESKTOP_SECURITY_STEPS = [
    ("Installing fail2ban for RDP brute-force protection", configure_fail2ban),
]

# Security and system hardening steps (common to all)
SECURITY_STEPS = [
    ("Configuring firewall", configure_firewall),
    ("Hardening SSH configuration", harden_ssh),
    ("Configuring automatic security updates", configure_auto_updates),
]

# CLI tools step (common to all)
CLI_STEPS = [
    ("Installing CLI tools", install_cli_tools),
]

# Desktop application steps
DESKTOP_APP_STEPS = [
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

# Workstation dev application steps
WORKSTATION_DEV_APP_STEPS = [
    ("Installing workstation dev applications", install_workstation_dev_apps),
    ("Configuring default browser", configure_vivaldi_browser),
]

# Step definitions with names for progress tracking
# Kept for backward compatibility
STEPS = [
    ("Ensuring sudo is installed", ensure_sudo_installed),
    ("Configuring UTF-8 locale", configure_locale),
    ("Setting up user", setup_user),
    ("Configuring time synchronization", configure_time_sync),
    ("Installing XFCE desktop environment", install_desktop),
    ("Installing xRDP", install_xrdp),
    ("Configuring audio for RDP", configure_audio),
    ("Configuring firewall", configure_firewall),
    ("Installing fail2ban for RDP brute-force protection", configure_fail2ban),
    ("Hardening SSH configuration", harden_ssh),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Installing CLI tools", install_cli_tools),
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]


def get_steps_for_system_type(system_type: str, skip_audio: bool = False) -> list:
    if system_type == "workstation_desktop":
        desktop_steps = DESKTOP_STEPS
        if skip_audio:
            desktop_steps = [s for s in DESKTOP_STEPS if s[1] != configure_audio]
        return COMMON_STEPS + desktop_steps + SECURITY_STEPS + \
               DESKTOP_SECURITY_STEPS + CLI_STEPS + DESKTOP_APP_STEPS
    elif system_type == "workstation_dev":
        # Workstation dev: no audio, different desktop apps (Vivaldi, VS Code)
        desktop_steps = [s for s in DESKTOP_STEPS if s[1] != configure_audio]
        return COMMON_STEPS + desktop_steps + SECURITY_STEPS + \
               DESKTOP_SECURITY_STEPS + CLI_STEPS + WORKSTATION_DEV_APP_STEPS
    elif system_type == "server_dev":
        return COMMON_STEPS + SECURITY_STEPS + CLI_STEPS
    else:
        raise ValueError(f"Unknown system type: {system_type}")
