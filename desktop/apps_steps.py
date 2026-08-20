"""Desktop and workstation setup steps."""

from __future__ import annotations

import os
import shlex
import tempfile

from lib.config import SetupConfig
from lib.machine_state import is_container
from lib.remote_utils import run, is_package_installed
from desktop.browser_steps import install_browser, is_flatpak_app_installed


FLATPAK_REMOTE = "flathub"


def is_flatpak_installed() -> bool:
    """Check if flatpak is installed."""
    result = run("which flatpak", check=False)
    return result.returncode == 0


def install_flatpak_if_needed() -> bool:
    """Install flatpak if not already installed.
    
    Returns:
        True if flatpak is available, False if installation failed or not recommended.
    """
    if is_container():
        print("  ⚠ Warning: Flatpak typically does not work well in unprivileged containers")
        print("    Consider using --machine vm or --machine hardware if Flatpak is needed")
    
    if is_flatpak_installed():
        return True

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    result = run("apt-get install -y -qq flatpak", check=False)
    if result.returncode != 0:
        print("  ⚠ Failed to install Flatpak")
        return False
    
    run(f"flatpak remote-add --if-not-exists {FLATPAK_REMOTE} https://flathub.org/repo/flathub.flatpakrepo", check=False)
    return True



def install_remmina(config: SetupConfig) -> None:
    """Install Remmina RDP client."""
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq remmina remmina-plugin-rdp remmina-plugin-vnc", check=False)
    if is_package_installed("remmina"):
        print("  ✓ Remmina installed/updated")


def install_office_apps(config: SetupConfig) -> None:
    """Install office suite (LibreOffice)."""
    if not config.install_office:
        return

    if config.use_flatpak:
        if not install_flatpak_if_needed():
            print("  Falling back to apt for LibreOffice installation")
            config.use_flatpak = False
        elif is_flatpak_app_installed("org.libreoffice.LibreOffice"):
            print("  ✓ LibreOffice already installed via Flatpak")
            return
        else:
            print("  Installing LibreOffice via Flatpak...")
            run(f"flatpak install -y {FLATPAK_REMOTE} org.libreoffice.LibreOffice", check=False)
            if is_flatpak_app_installed("org.libreoffice.LibreOffice"):
                print("  ✓ LibreOffice installed via Flatpak")
            return
    
    if is_package_installed("libreoffice"):
        print("  ✓ LibreOffice already installed")
        return
    print("  Installing LibreOffice...")
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq libreoffice", check=False)
    if is_package_installed("libreoffice"):
        print("  ✓ LibreOffice installed")


def install_desktop_apps(config: SetupConfig) -> None:
    install_browser(config)
    install_office_apps(config)
    
    use_flatpak = config.use_flatpak
    if use_flatpak:
        if not install_flatpak_if_needed():
            print("  Falling back to apt for desktop app installation")
            use_flatpak = False
    
    if use_flatpak:
        if is_flatpak_app_installed("com.discordapp.Discord"):
            print("  ✓ Other desktop apps already installed via Flatpak")
            return
        
        print("  Installing other desktop apps via Flatpak...")

        if not is_flatpak_app_installed("com.discordapp.Discord"):
            print("  Installing Discord...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.discordapp.Discord", check=False)
        
        if is_flatpak_app_installed("com.discordapp.Discord"):
            print("  ✓ Other desktop apps installed via Flatpak (Discord)")
    else:
        discord_installed = is_package_installed("discord")

        if discord_installed:
            print("  ✓ Other desktop apps already installed")
            return

        print("  Installing Discord...")
        with tempfile.TemporaryDirectory(prefix="infra-tools-discord-") as temporary_dir:
            package_path = os.path.join(temporary_dir, "discord.deb")
            download_result = run(
                "wget --https-only -qO "
                f"{shlex.quote(package_path)} "
                "'https://discord.com/api/download?platform=linux&format=deb'",
                check=False,
            )
            if download_result.returncode != 0:
                print("  ⚠ Failed to download Discord")
                return
            os.environ["DEBIAN_FRONTEND"] = "noninteractive"
            run(f"apt-get install -y -qq {shlex.quote(package_path)}", check=False)
        discord_installed = is_package_installed("discord")

        if discord_installed:
            print("  ✓ Other desktop apps installed (Discord)")


def install_workstation_dev_apps(config: SetupConfig) -> None:
    install_browser(config)
    
    use_flatpak = config.use_flatpak
    if use_flatpak:
        if not install_flatpak_if_needed():
            print("  Falling back to apt for VS Code installation")
            use_flatpak = False
    
    if use_flatpak:
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
        from desktop.browser_steps import _install_via_extrepo
        if _install_via_extrepo("VS Code", "vscode", "code"):
            print("  ✓ Workstation dev apps installed (VS Code)")
