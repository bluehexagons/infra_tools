"""Desktop and workstation setup steps."""

from __future__ import annotations
from typing import Optional
import os
import shlex

from lib.config import SetupConfig
from lib.machine_state import is_container
from lib.remote_utils import run, is_package_installed, is_flatpak_app_installed, file_contains


FLATPAK_REMOTE = "flathub"

def install_single_browser(browser: str, use_flatpak: bool) -> None:
    """Install a single browser."""
    if browser == "brave":
        if use_flatpak:
            if is_flatpak_app_installed("com.brave.Browser"):
                print("  ✓ Brave browser already installed")
                return
            print("  Installing Brave browser...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.brave.Browser", check=False)
        else:
            if is_package_installed("brave-browser"):
                print("  ✓ Brave browser already installed")
                return
            print("  Installing Brave browser...")
            if not os.path.exists("/usr/share/keyrings/brave-browser-archive-keyring.gpg"):
                run("apt-get install -y -qq curl gnupg")
                run("curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg", check=False)
                run('echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" > /etc/apt/sources.list.d/brave-browser-release.list', check=False)
                run("apt-get update -qq", check=False)
            run("apt-get install -y -qq brave-browser", check=False)
        print("  ✓ Brave browser installed")
    
    elif browser == "firefox":
        if use_flatpak:
            if is_flatpak_app_installed("org.mozilla.firefox"):
                print("  ✓ Firefox already installed")
                return
            print("  Installing Firefox...")
            run(f"flatpak install -y {FLATPAK_REMOTE} org.mozilla.firefox", check=False)
        else:
            if is_package_installed("firefox") or is_package_installed("firefox-esr"):
                print("  ✓ Firefox already installed")
                return
            print("  Installing Firefox...")
            run("apt-get install -y -qq firefox-esr", check=False)
        
        print("  Installing uBlock Origin extension for Firefox...")
        run("wget -qO /tmp/ublock_origin.xpi https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi", check=False)
        print("  ✓ Firefox installed (uBlock Origin downloaded to /tmp/ublock_origin.xpi)")
    
    elif browser == "librewolf":
        if use_flatpak:
            if is_flatpak_app_installed("io.gitlab.librewolf-community"):
                print("  ✓ LibreWolf browser already installed")
                return
            print("  Installing LibreWolf browser...")
            run(f"flatpak install -y {FLATPAK_REMOTE} io.gitlab.librewolf-community", check=False)
        else:
            if is_package_installed("librewolf"):
                print("  ✓ LibreWolf browser already installed")
                return
            print("  Installing LibreWolf browser...")
            if not os.path.exists("/usr/share/keyrings/librewolf.gpg"):
                run("apt-get install -y -qq curl gnupg")
                run("curl -fsSL https://deb.librewolf.net/keyring.gpg | gpg --dearmor --output /usr/share/keyrings/librewolf.gpg", check=False)
                run('echo "deb [signed-by=/usr/share/keyrings/librewolf.gpg] http://deb.librewolf.net bookworm main" > /etc/apt/sources.list.d/librewolf.list', check=False)
                run("apt-get update -qq", check=False)
            run("apt-get install -y -qq librewolf", check=False)
        print("  ✓ LibreWolf browser installed")
    
    elif browser == "browsh":
        print("  Installing Browsh (requires Firefox)...")
        if not (is_package_installed("firefox") or is_package_installed("firefox-esr")):
            print("  Installing Firefox (required for Browsh)...")
            run("apt-get install -y -qq firefox-esr", check=False)
        
        if not os.path.exists("/usr/local/bin/browsh"):
            run("wget -qO /tmp/browsh.deb https://github.com/browsh-org/browsh/releases/download/v1.8.0/browsh_1.8.0_linux_amd64.deb", check=False)
            run("apt-get install -y -qq /tmp/browsh.deb", check=False)
            run("rm -f /tmp/browsh.deb", check=False)
        print("  ✓ Browsh installed")
    
    elif browser == "vivaldi":
        if use_flatpak:
            if is_flatpak_app_installed("com.vivaldi.Vivaldi"):
                print("  ✓ Vivaldi browser already installed")
                return
            print("  Installing Vivaldi browser...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.vivaldi.Vivaldi", check=False)
        else:
            if is_package_installed("vivaldi-stable"):
                print("  ✓ Vivaldi browser already installed")
                return
            print("  Installing Vivaldi browser...")
            if not os.path.exists("/usr/share/keyrings/vivaldi-archive-keyring.gpg"):
                run("apt-get install -y -qq curl gnupg")
                run("curl -fsSL https://repo.vivaldi.com/archive/linux_signing_key.pub | gpg --dearmor --output /usr/share/keyrings/vivaldi-archive-keyring.gpg", check=False)
                run('echo "deb [signed-by=/usr/share/keyrings/vivaldi-archive-keyring.gpg] https://repo.vivaldi.com/archive/deb/ stable main" > /etc/apt/sources.list.d/vivaldi.list', check=False)
                run("apt-get update -qq", check=False)
            run("apt-get install -y -qq vivaldi-stable", check=False)
        print("  ✓ Vivaldi browser installed")
    
    elif browser == "lynx":
        if is_package_installed("lynx"):
            print("  ✓ Lynx already installed")
            return
        print("  Installing Lynx...")
        run("apt-get install -y -qq lynx", check=False)
        print("  ✓ Lynx installed")


def install_browser(config: SetupConfig) -> None:
    """Install the specified browser(s)."""
    # In containers, prefer apt over Flatpak since Flatpak often doesn't work
    use_flatpak = config.use_flatpak
    if use_flatpak and is_container():
        print("  ⚠ Container detected: using apt instead of Flatpak for browser")
        use_flatpak = False
    
    # Install multiple browsers if specified
    if config.browsers:
        for browser in config.browsers:
            install_single_browser(browser, use_flatpak)
    elif config.browser:
        install_single_browser(config.browser, use_flatpak)


def configure_default_browser(config: SetupConfig) -> None:
    if not config.browser:
        return

    safe_username = shlex.quote(config.username)
    mimeapps_path = f"/home/{config.username}/.config/mimeapps.list"
    
    browser_desktops: dict[str, Optional[str]] = {
        "brave": "brave-browser.desktop",
        "firefox": "firefox.desktop",
        "librewolf": "librewolf.desktop",
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


def configure_vivaldi_browser(config: SetupConfig) -> None:
    """Configure Vivaldi browser as default (wrapper for configure_default_browser)."""
    configure_default_browser(config)
