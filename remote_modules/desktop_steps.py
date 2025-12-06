"""Desktop and workstation setup steps."""

import os
import shlex

from .utils import run, is_package_installed, is_service_active, file_contains


def install_desktop(os_type: str, desktop: str = "xfce", **_) -> None:
    if desktop == "xfce":
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    elif desktop == "i3":
        package = "i3"
        install_cmd = "apt-get install -y -qq i3 i3status i3lock dmenu"
    elif desktop == "cinnamon":
        package = "cinnamon"
        install_cmd = "apt-get install -y -qq cinnamon cinnamon-core"
    else:
        print(f"  ⚠ Unknown desktop environment: {desktop}, defaulting to XFCE")
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    
    if is_package_installed(package, os_type):
        print(f"  ✓ {desktop.upper()} desktop already installed")
        return
    
    run(install_cmd)
    print(f"  ✓ {desktop.upper()} desktop installed")


def install_xrdp(username: str, os_type: str, desktop: str = "xfce", **_) -> None:
    safe_username = shlex.quote(username)
    xsession_path = f"/home/{username}/.xsession"
    
    if desktop == "xfce":
        session_cmd = "xfce4-session"
    elif desktop == "i3":
        session_cmd = "i3"
    elif desktop == "cinnamon":
        session_cmd = "cinnamon-session"
    else:
        session_cmd = "xfce4-session"
    
    if is_package_installed("xrdp", os_type) and os.path.exists(xsession_path):
        if is_service_active("xrdp"):
            print("  ✓ xRDP already installed and configured")
            return

    if not is_package_installed("xrdp", os_type):
        run("apt-get install -y -qq xrdp")
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)

    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    with open(xsession_path, "w") as f:
        f.write(f"{session_cmd}\n")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured")


def harden_xrdp(os_type: str, **_) -> None:
    """Harden xRDP with TLS encryption and group restrictions."""
    xrdp_config = "/etc/xrdp/xrdp.ini"
    sesman_config = "/etc/xrdp/sesman.ini"
    
    if not os.path.exists(xrdp_config):
        print("  ⚠ xRDP not installed, skipping hardening")
        return
    
    if (file_contains(xrdp_config, "security_layer=tls") and
        file_contains(sesman_config, "AllowGroups=remoteusers") and
        file_contains(sesman_config, "DenyUsers=root")):
        print("  ✓ xRDP already hardened")
        return
    
    run(f"sed -i 's/^#\\?security_layer=.*/security_layer=tls/' {xrdp_config}")
    run(f"sed -i 's/^#\\?crypt_level=.*/crypt_level=high/' {xrdp_config}")
    
    if not file_contains(xrdp_config, "security_layer"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a security_layer=tls' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\nsecurity_layer=tls' {xrdp_config}")
    
    if not file_contains(xrdp_config, "crypt_level"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a crypt_level=high' {xrdp_config}")
        else:
            run(f"sed -i '1i crypt_level=high' {xrdp_config}")
    
    if not file_contains(sesman_config, "[Security]"):
        run(f"echo '\n[Security]' >> {sesman_config}")
    
    if not file_contains(sesman_config, "AllowGroups"):
        run(f"sed -i '/\\[Security\\]/a AllowGroups=remoteusers' {sesman_config}")
    
    if not file_contains(sesman_config, "DenyUsers"):
        run(f"sed -i '/\\[Security\\]/a DenyUsers=root' {sesman_config}")
    
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    
    run("systemctl restart xrdp")
    run("systemctl restart xrdp-sesman", check=False)
    
    print("  ✓ xRDP hardened (TLS encryption, root denied, restricted to remoteusers group)")



def configure_audio(username: str, os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    home_dir = f"/home/{username}"
    pulse_dir = f"{home_dir}/.config/pulse"
    client_conf = f"{pulse_dir}/client.conf"
    
    if os.path.exists(client_conf) and is_package_installed("pulseaudio", os_type):
        print("  ✓ Audio already configured")
        return

    run("apt-get install -y -qq pulseaudio pulseaudio-utils")
    run("apt-get install -y -qq build-essential dpkg-dev libpulse-dev git autoconf libtool", check=False)
    
    module_dir = "/tmp/pulseaudio-module-xrdp"
    if not os.path.exists(module_dir):
        run(f"git clone https://github.com/neutrinolabs/pulseaudio-module-xrdp.git {module_dir}", check=False)
    
    run(f"cd {module_dir} && ./bootstrap", check=False)
    run(f"cd {module_dir} && ./configure PULSE_DIR=/usr/include/pulse", check=False)
    run(f"cd {module_dir} && make", check=False)
    run(f"cd {module_dir} && make install", check=False)
    
    run(f"usermod -aG audio {safe_username}", check=False)
    
    os.makedirs(pulse_dir, exist_ok=True)
    
    with open(client_conf, "w") as f:
        f.write("autospawn = yes\n")
        f.write("daemon-binary = /usr/bin/pulseaudio\n")
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(pulse_dir)}")
    run("systemctl restart xrdp", check=False)
    
    print("  ✓ Audio configured (PulseAudio + xRDP module)")


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
        run("apt-get install -y -qq libreoffice")
    else:
        print("  ✓ LibreOffice already installed")

    print("  Installing Brave browser...")
    if not os.path.exists("/usr/share/keyrings/brave-browser-archive-keyring.gpg"):
        run("apt-get install -y -qq curl gnupg")
        run("curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg", check=False)
        run('echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" > /etc/apt/sources.list.d/brave-browser-release.list', check=False)
        run("apt-get update -qq", check=False)
    if not is_package_installed("brave-browser", os_type):
        run("apt-get install -y -qq brave-browser", check=False)

    print("  Installing VSCodium...")
    if not os.path.exists("/usr/share/keyrings/vscodium-archive-keyring.gpg"):
        run("wget -qO - https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/raw/master/pub.gpg | gpg --dearmor | dd of=/usr/share/keyrings/vscodium-archive-keyring.gpg 2>/dev/null", check=False)
        run('echo "deb [signed-by=/usr/share/keyrings/vscodium-archive-keyring.gpg] https://download.vscodium.com/debs vscodium main" > /etc/apt/sources.list.d/vscodium.list', check=False)
        run("apt-get update -qq", check=False)
    if not is_package_installed("codium", os_type):
        run("apt-get install -y -qq codium", check=False)

    print("  Installing Discord...")
    if not is_package_installed("discord", os_type):
        run("wget -qO /tmp/discord.deb 'https://discord.com/api/download?platform=linux&format=deb'", check=False)
        run("apt-get install -y -qq /tmp/discord.deb", check=False)
        run("rm -f /tmp/discord.deb", check=False)

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
    if not os.path.exists("/usr/share/keyrings/vivaldi-archive-keyring.gpg"):
        run("apt-get install -y -qq curl gnupg")
        run("curl -fsSL https://repo.vivaldi.com/archive/linux_signing_key.pub | gpg --dearmor --output /usr/share/keyrings/vivaldi-archive-keyring.gpg", check=False)
        run('echo "deb [signed-by=/usr/share/keyrings/vivaldi-archive-keyring.gpg] https://repo.vivaldi.com/archive/deb/ stable main" > /etc/apt/sources.list.d/vivaldi.list', check=False)
        run("apt-get update -qq", check=False)
    if not is_package_installed("vivaldi-stable", os_type):
        run("apt-get install -y -qq vivaldi-stable", check=False)

    print("  Installing Visual Studio Code...")
    if not os.path.exists("/etc/apt/trusted.gpg.d/microsoft.gpg"):
        run("apt-get install -y -qq wget gpg")
        run("wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --output /etc/apt/trusted.gpg.d/microsoft.gpg", check=False)
        run('echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list', check=False)
        run("apt-get update -qq", check=False)
    if not is_package_installed("code", os_type):
        run("apt-get install -y -qq code", check=False)

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


def configure_gnome_keyring(username: str, os_type: str, **_) -> None:
    """Configure gnome-keyring for desktop setups."""
    safe_username = shlex.quote(username)
    
    if is_package_installed("gnome-keyring", os_type):
        print("  ✓ gnome-keyring already installed")
        return
    
    run("apt-get install -y -qq gnome-keyring libpam-gnome-keyring")
    
    pam_password = "/etc/pam.d/common-password"
    pam_session = "/etc/pam.d/common-session"
    
    if os.path.exists(pam_password) and not file_contains(pam_password, "pam_gnome_keyring.so"):
        with open(pam_password, "a") as f:
            f.write("password optional pam_gnome_keyring.so\n")
    
    if os.path.exists(pam_session) and not file_contains(pam_session, "pam_gnome_keyring.so"):
        with open(pam_session, "a") as f:
            f.write("session optional pam_gnome_keyring.so auto_start\n")
    
    home_dir = f"/home/{username}"
    profile_path = f"{home_dir}/.profile"
    
    # The eval command is the official way to start gnome-keyring-daemon
    # as documented in gnome-keyring documentation. It exports required
    # environment variables like SSH_AUTH_SOCK for SSH agent integration.
    keyring_env = """
# Start gnome-keyring-daemon
if [ -n "$DESKTOP_SESSION" ]; then
    eval $(gnome-keyring-daemon --start --components=pkcs11,secrets,ssh)
    export SSH_AUTH_SOCK
fi
"""
    
    if os.path.exists(profile_path):
        if not file_contains(profile_path, "gnome-keyring-daemon"):
            with open(profile_path, "a") as f:
                f.write(keyring_env)
        run(f"chown {safe_username}:{safe_username} {shlex.quote(profile_path)}")
    else:
        with open(profile_path, "w") as f:
            f.write(keyring_env)
        run(f"chown {safe_username}:{safe_username} {shlex.quote(profile_path)}")
    
    print("  ✓ gnome-keyring configured (auto-unlock on login, SSH agent integration)")
