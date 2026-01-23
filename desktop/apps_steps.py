"""Desktop and workstation setup steps."""

from __future__ import annotations
from typing import Optional
import os
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, is_service_active, file_contains


FLATPAK_REMOTE = "flathub"


def is_flatpak_installed() -> bool:
    """Check if flatpak is installed."""
    result = run("which flatpak", check=False)
    return result.returncode == 0


def install_flatpak_if_needed() -> None:
    """Install flatpak if not already installed."""
    if is_flatpak_installed():
        return
    run("apt-get install -y -qq flatpak")
    run(f"flatpak remote-add --if-not-exists {FLATPAK_REMOTE} https://flathub.org/repo/flathub.flatpakrepo", check=False)


def is_flatpak_app_installed(app_id: str) -> bool:
    """Check if a flatpak app is installed."""
    result = run(f"flatpak info {shlex.quote(app_id)}", check=False)
    return result.returncode == 0

def install_remmina(config: SetupConfig) -> None:
    """Install Remmina RDP client."""
    run("apt-get install -y -qq remmina remmina-plugin-rdp remmina-plugin-vnc")
    print("  ✓ Remmina installed/updated")


def install_office_apps(config: SetupConfig) -> None:
    """Install office suite (LibreOffice)."""
    if not config.install_office:
        return

    if config.use_flatpak:
        install_flatpak_if_needed()
        if is_flatpak_app_installed("org.libreoffice.LibreOffice"):
            print("  ✓ LibreOffice already installed via Flatpak")
            return
        print("  Installing LibreOffice via Flatpak...")
        run(f"flatpak install -y {FLATPAK_REMOTE} org.libreoffice.LibreOffice", check=False)
        print("  ✓ LibreOffice installed via Flatpak")
    else:
        if is_package_installed("libreoffice"):
            print("  ✓ LibreOffice already installed")
            return
        print("  Installing LibreOffice...")
        run("apt-get install -y -qq libreoffice")
        print("  ✓ LibreOffice installed")


def install_desktop_apps(config: SetupConfig) -> None:
    install_browser(config)
    install_office_apps(config)
    
    if config.use_flatpak:
        install_flatpak_if_needed()
        
        all_installed = (
            is_flatpak_app_installed("com.vscodium.codium") and
            is_flatpak_app_installed("com.discordapp.Discord")
        )
        
        if all_installed:
            print("  ✓ Other desktop apps already installed via Flatpak")
            return
        
        print("  Installing other desktop apps via Flatpak...")
        
        if not is_flatpak_app_installed("com.vscodium.codium"):
            print("  Installing VSCodium...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.vscodium.codium", check=False)
        
        if not is_flatpak_app_installed("com.discordapp.Discord"):
            print("  Installing Discord...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.discordapp.Discord", check=False)
        
        print(f"  ✓ Other desktop apps installed via Flatpak (VSCodium, Discord)")
    else:
        all_installed = is_package_installed("codium") and is_package_installed("discord")
        
        if all_installed:
            print("  ✓ Other desktop apps already installed")
            return

        print("  Installing VSCodium...")
        if not os.path.exists("/usr/share/keyrings/vscodium-archive-keyring.gpg"):
            run("wget -qO - https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/raw/master/pub.gpg | gpg --dearmor | dd of=/usr/share/keyrings/vscodium-archive-keyring.gpg 2>/dev/null", check=False)
            run('echo "deb [signed-by=/usr/share/keyrings/vscodium-archive-keyring.gpg] https://download.vscodium.com/debs vscodium main" > /etc/apt/sources.list.d/vscodium.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("codium"):
            run("apt-get install -y -qq codium", check=False)

        print("  Installing Discord...")
        if not is_package_installed("discord"):
            run("wget -qO /tmp/discord.deb 'https://discord.com/api/download?platform=linux&format=deb'", check=False)
            run("apt-get install -y -qq /tmp/discord.deb", check=False)
            run("rm -f /tmp/discord.deb", check=False)

        print(f"  ✓ Other desktop apps installed (VSCodium, Discord)")



def configure_default_browser(config: SetupConfig) -> None:
    if not config.browser:
        return

    safe_username = shlex.quote(config.username)
    mimeapps_path = f"/home/{config.username}/.config/mimeapps.list"
    
    browser_desktops: dict[str, Optional[str]] = {
        "brave": "brave-browser.desktop",
        "firefox": "firefox.desktop",
        "vivaldi": "vivaldi-stable.desktop",
        "lynx": None,
        "browsh": None
    }
    
    desktop_file = browser_desktops.get(config.browser)
    if not desktop_file:
        print(f"  ✓ No default browser configuration needed for {config.browser}")
        return
    
    if os.path.exists(mimeapps_path):
        if file_contains(mimeapps_path, desktop_file):
            print("  ✓ Default browser already set")
            return
    
    user_apps_dir = f"/home/{config.username}/.local/share/applications"
    os.makedirs(user_apps_dir, exist_ok=True)
    run(f"chown -R {safe_username}:{safe_username} /home/{config.username}/.local")
    
    os.makedirs(f"/home/{config.username}/.config", exist_ok=True)
    
    mimeapps_content = f"""[Default Applications]
x-scheme-handler/http={desktop_file}
x-scheme-handler/https={desktop_file}
text/html={desktop_file}
application/xhtml+xml={desktop_file}
"""
    
    with open(mimeapps_path, "w") as f:
        f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} /home/{config.username}/.config")
    
    run(f"xdg-mime default {desktop_file} x-scheme-handler/http", check=False)
    run(f"xdg-mime default {desktop_file} x-scheme-handler/https", check=False)
    
    print(f"  ✓ Default browser set to {config.browser.capitalize()}")


def install_workstation_dev_apps(config: SetupConfig) -> None:
    install_browser(config)
    
    if config.use_flatpak:
        install_flatpak_if_needed()
        
        if is_flatpak_app_installed("com.visualstudio.code"):
            print("  ✓ Workstation dev apps already installed via Flatpak")
            return
        
        print("  Installing workstation dev apps via Flatpak...")
        
        if not is_flatpak_app_installed("com.visualstudio.code"):
            print("  Installing Visual Studio Code...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.visualstudio.code", check=False)
        
        print("  ✓ Workstation dev apps installed via Flatpak (VS Code)")
    else:
        if is_package_installed("code") or os.path.exists("/usr/bin/code"):
            print("  ✓ Workstation dev apps already installed")
            return

        print("  Installing Visual Studio Code...")
        if not os.path.exists("/etc/apt/trusted.gpg.d/microsoft.gpg"):
            run("apt-get install -y -qq wget gpg")
            run("wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --output /etc/apt/trusted.gpg.d/microsoft.gpg", check=False)
            run('echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("code"):
            run("apt-get install -y -qq code", check=False)

        print("  ✓ Workstation dev apps installed (VS Code)")


def configure_vivaldi_browser(config: SetupConfig) -> None:
    configure_default_browser(config)


def configure_gnome_keyring(config: SetupConfig) -> None:
    """Configure gnome-keyring for desktop setups."""
    safe_username = shlex.quote(config.username)
    
    # Install keyring packages for password storage and auto-unlock
    run("apt-get install -y -qq gnome-keyring libpam-gnome-keyring libsecret-tools")
    
    pam_auth = "/etc/pam.d/common-auth"
    pam_password = "/etc/pam.d/common-password"
    pam_session = "/etc/pam.d/common-session"
    
    # Add auth line to capture login password for keyring auto-unlock
    if os.path.exists(pam_auth) and not file_contains(pam_auth, "pam_gnome_keyring.so"):
        with open(pam_auth, "a") as f:
            f.write("auth optional pam_gnome_keyring.so\n")
    
    if os.path.exists(pam_password) and not file_contains(pam_password, "pam_gnome_keyring.so"):
        with open(pam_password, "a") as f:
            f.write("password optional pam_gnome_keyring.so\n")
    
    if os.path.exists(pam_session) and not file_contains(pam_session, "pam_gnome_keyring.so"):
        with open(pam_session, "a") as f:
            f.write("session optional pam_gnome_keyring.so auto_start\n")
    
    home_dir = f"/home/{config.username}"
    profile_path = f"{home_dir}/.profile"
    
    keyring_env = """
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
    
    print("  ✓ gnome-keyring installed/configured (auto-unlock on login, SSH agent integration)")
    print("    - IMPORTANT: For auto-unlock to work:")
    print("      1. Delete old keyring: rm ~/.local/share/keyrings/login.keyring")
    print("      2. Log out and log back in - new keyring will be created with login password")
    print("    - Tip: Install 'seahorse' package if you need a GUI to manage keyrings")



def install_remmina(config: SetupConfig) -> None:
    """Install Remmina RDP client."""
    run("apt-get install -y -qq remmina remmina-plugin-rdp remmina-plugin-vnc")
    print("  ✓ Remmina installed/updated")


def install_office_apps(config: SetupConfig) -> None:
    """Install office suite (LibreOffice)."""
    if not config.install_office:
        return

    if config.use_flatpak:
        install_flatpak_if_needed()
        if is_flatpak_app_installed("org.libreoffice.LibreOffice"):
            print("  ✓ LibreOffice already installed via Flatpak")
            return
        print("  Installing LibreOffice via Flatpak...")
        run(f"flatpak install -y {FLATPAK_REMOTE} org.libreoffice.LibreOffice", check=False)
        print("  ✓ LibreOffice installed via Flatpak")
    else:
        if is_package_installed("libreoffice"):
            print("  ✓ LibreOffice already installed")
            return
        print("  Installing LibreOffice...")
        run("apt-get install -y -qq libreoffice")
        print("  ✓ LibreOffice installed")


def install_desktop_apps(config: SetupConfig) -> None:
    install_browser(config)
    install_office_apps(config)
    
    if config.use_flatpak:
        install_flatpak_if_needed()
        
        all_installed = (
            is_flatpak_app_installed("com.vscodium.codium") and
            is_flatpak_app_installed("com.discordapp.Discord")
        )
        
        if all_installed:
            print("  ✓ Other desktop apps already installed via Flatpak")
            return
        
        print("  Installing other desktop apps via Flatpak...")
        
        if not is_flatpak_app_installed("com.vscodium.codium"):
            print("  Installing VSCodium...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.vscodium.codium", check=False)
        
        if not is_flatpak_app_installed("com.discordapp.Discord"):
            print("  Installing Discord...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.discordapp.Discord", check=False)
        
        print(f"  ✓ Other desktop apps installed via Flatpak (VSCodium, Discord)")
    else:
        all_installed = is_package_installed("codium") and is_package_installed("discord")
        
        if all_installed:
            print("  ✓ Other desktop apps already installed")
            return

        print("  Installing VSCodium...")
        if not os.path.exists("/usr/share/keyrings/vscodium-archive-keyring.gpg"):
            run("wget -qO - https://gitlab.com/paulcarroty/vscodium-deb-rpm-repo/raw/master/pub.gpg | gpg --dearmor | dd of=/usr/share/keyrings/vscodium-archive-keyring.gpg 2>/dev/null", check=False)
            run('echo "deb [signed-by=/usr/share/keyrings/vscodium-archive-keyring.gpg] https://download.vscodium.com/debs vscodium main" > /etc/apt/sources.list.d/vscodium.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("codium"):
            run("apt-get install -y -qq codium", check=False)

        print("  Installing Discord...")
        if not is_package_installed("discord"):
            run("wget -qO /tmp/discord.deb 'https://discord.com/api/download?platform=linux&format=deb'", check=False)
            run("apt-get install -y -qq /tmp/discord.deb", check=False)
            run("rm -f /tmp/discord.deb", check=False)

        print(f"  ✓ Other desktop apps installed (VSCodium, Discord)")



def install_workstation_dev_apps(config: SetupConfig) -> None:
    install_browser(config)
    
    if config.use_flatpak:
        install_flatpak_if_needed()
        
        if is_flatpak_app_installed("com.visualstudio.code"):
            print("  ✓ Workstation dev apps already installed via Flatpak")
            return
        
        print("  Installing workstation dev apps via Flatpak...")
        
        if not is_flatpak_app_installed("com.visualstudio.code"):
            print("  Installing Visual Studio Code...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.visualstudio.code", check=False)
        
        print("  ✓ Workstation dev apps installed via Flatpak (VS Code)")
    else:
        if is_package_installed("code") or os.path.exists("/usr/bin/code"):
            print("  ✓ Workstation dev apps already installed")
            return

        print("  Installing Visual Studio Code...")
        if not os.path.exists("/etc/apt/trusted.gpg.d/microsoft.gpg"):
            run("apt-get install -y -qq wget gpg")
            run("wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --output /etc/apt/trusted.gpg.d/microsoft.gpg", check=False)
            run('echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list', check=False)
            run("apt-get update -qq", check=False)
        if not is_package_installed("code"):
            run("apt-get install -y -qq code", check=False)

        print("  ✓ Workstation dev apps installed (VS Code)")



