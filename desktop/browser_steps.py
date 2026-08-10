"""Desktop and workstation setup steps."""

from __future__ import annotations
from typing import Optional
import os
import shlex
import subprocess

from lib.config import SetupConfig
from lib.machine_state import is_container
from lib.remote_utils import (
    file_contains,
    get_user_home,
    is_dry_run,
    is_package_installed,
    run,
)


FLATPAK_REMOTE = "flathub"
_apt_update_done = False
HELIUM_RELEASE_API = "https://api.github.com/repos/imputnet/helium-linux/releases/latest"


def is_flatpak_app_installed(app_id: str) -> bool:
    """Check if a Flatpak application is installed."""
    result = subprocess.run(
        ["flatpak", "list", "--app", "--columns=application"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    return app_id in result.stdout.splitlines()


def _ensure_extrepo_and_update() -> None:
    """Install extrepo if needed and run apt-get update only once."""
    global _apt_update_done
    if not is_package_installed("extrepo"):
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get install -y -qq extrepo", check=False)
    if not _apt_update_done:
        run("apt-get update -qq", check=False)
        _apt_update_done = True


def _install_via_extrepo(name: str, extrepo_name: str, package_name: str) -> bool:
    """Install a package via extrepo. Returns True if successful."""
    _ensure_extrepo_and_update()
    run(f"extrepo enable {extrepo_name}", check=False)
    run("apt-get update -qq", check=False)
    sources_path = f"/etc/apt/sources.list.d/extrepo_{extrepo_name}.sources"
    if os.path.exists(sources_path):
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run(f"apt-get install -y -qq {package_name}", check=False)
        if is_package_installed(package_name):
            return True
        print(f"  ✗ Failed to install {name} (package not found after install)")
    else:
        print(f"  ✗ Failed to enable {name} repository")
    return False


def _install_helium_browser() -> None:
    """Install Helium from the latest upstream Debian package release."""
    if is_package_installed("helium-bin") or os.path.exists("/usr/bin/helium"):
        print("  ✓ Helium browser already installed")
        return

    print("  Installing Helium browser...")
    url_script = f"""import json
import subprocess
import sys
import urllib.request

arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
if arch not in {{"amd64", "arm64"}}:
    sys.exit(f"unsupported architecture: {{arch}}")

with urllib.request.urlopen("{HELIUM_RELEASE_API}", timeout=30) as response:
    release = json.load(response)

suffix = f"_{{arch}}.deb"
for asset in release.get("assets", []):
    name = asset.get("name", "")
    if name.startswith("helium-bin_") and name.endswith(suffix):
        print(asset["browser_download_url"])
        break
else:
    sys.exit(f"no Helium Debian package found for {{arch}}")
"""
    result = run(
        f"python3 -c {shlex.quote(url_script)}",
        check=False,
        capture_output=True,
        display_cmd="python3 -c '[resolve latest Helium Debian package URL]'",
    )
    helium_url = result.stdout.strip() if result.returncode == 0 else ""
    if not helium_url:
        print("  ✗ Failed to resolve latest Helium package URL")
        if result.stderr:
            print(f"    {result.stderr.strip()[:200]}")
        return

    run(f"wget -qO /tmp/helium.deb {shlex.quote(helium_url)}", check=False)
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq /tmp/helium.deb", check=False)
    run("rm -f /tmp/helium.deb", check=False)
    if is_package_installed("helium-bin") or os.path.exists("/usr/bin/helium"):
        print("  ✓ Helium browser installed")


def install_single_browser(browser: str, use_flatpak: bool) -> None:
    """Install a single browser."""
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    if browser == "brave":
        if use_flatpak:
            if is_flatpak_app_installed("com.brave.Browser"):
                print("  ✓ Brave browser already installed")
                return
            print("  Installing Brave browser...")
            run(f"flatpak install -y {FLATPAK_REMOTE} com.brave.Browser", check=False)
            if is_flatpak_app_installed("com.brave.Browser"):
                print("  ✓ Brave browser installed")
                return
            print("  ⚠ Flatpak install failed, falling back to apt...")
        
        if is_package_installed("brave-browser"):
            print("  ✓ Brave browser already installed")
            return
        print("  Installing Brave browser...")
        if _install_via_extrepo("Brave", "brave", "brave-browser"):
            print("  ✓ Brave browser installed")
    
    elif browser == "firefox":
        if use_flatpak:
            if is_flatpak_app_installed("org.mozilla.firefox"):
                print("  ✓ Firefox already installed")
                return
            print("  Installing Firefox...")
            run(f"flatpak install -y {FLATPAK_REMOTE} org.mozilla.firefox", check=False)
            if is_flatpak_app_installed("org.mozilla.firefox"):
                print("  ✓ Firefox installed")
                return
        else:
            if is_package_installed("firefox") or is_package_installed("firefox-esr"):
                print("  ✓ Firefox already installed")
                return
            print("  Installing Firefox...")
            run("apt-get install -y -qq firefox-esr", check=False)
            if is_package_installed("firefox") or is_package_installed("firefox-esr"):
                print("  ✓ Firefox installed")
            else:
                return
        
        print("  Installing uBlock Origin extension for Firefox...")
        run("wget -qO /tmp/ublock_origin.xpi https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi", check=False)
        if os.path.exists("/tmp/ublock_origin.xpi"):
            print("  ✓ Firefox installed (uBlock Origin downloaded to /tmp/ublock_origin.xpi)")
    
    elif browser == "librewolf":
        if use_flatpak:
            if is_flatpak_app_installed("io.gitlab.librewolf-community"):
                print("  ✓ LibreWolf browser already installed")
                return
            print("  Installing LibreWolf browser...")
            run(f"flatpak install -y {FLATPAK_REMOTE} io.gitlab.librewolf-community", check=False)
            if is_flatpak_app_installed("io.gitlab.librewolf-community"):
                print("  ✓ LibreWolf browser installed")
                return
        else:
            if is_package_installed("librewolf"):
                print("  ✓ LibreWolf browser already installed")
                return
            print("  Installing LibreWolf browser...")

            if _install_via_extrepo("LibreWolf", "librewolf", "librewolf"):
                print("  ✓ LibreWolf browser installed")

    elif browser == "helium":
        _install_helium_browser()
    
    elif browser == "browsh":
        print("  Installing Browsh (requires Firefox)...")
        if not (is_package_installed("firefox") or is_package_installed("firefox-esr")):
            print("  Installing Firefox (required for Browsh)...")
            run("apt-get install -y -qq firefox-esr", check=False)
        
        if not os.path.exists("/usr/local/bin/browsh"):
            run("wget -qO /tmp/browsh.deb https://github.com/browsh-org/browsh/releases/download/v1.8.0/browsh_1.8.0_linux_amd64.deb", check=False)
            run("apt-get install -y -qq /tmp/browsh.deb", check=False)
            run("rm -f /tmp/browsh.deb", check=False)
        if os.path.exists("/usr/local/bin/browsh"):
            print("  ✓ Browsh installed")
    
    elif browser == "lynx":
        if is_package_installed("lynx"):
            print("  ✓ Lynx already installed")
            return
        print("  Installing Lynx...")
        run("apt-get install -y -qq lynx", check=False)
        if is_package_installed("lynx"):
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

    if is_dry_run():
        print(f"  [DRY-RUN] Would set {config.browser} as the default browser")
        return

    safe_username = shlex.quote(config.username)
    home_dir = get_user_home(config.username)
    mimeapps_path = os.path.join(home_dir, ".config", "mimeapps.list")
    
    browser_desktops: dict[str, Optional[str]] = {
        "brave": "brave-browser.desktop",
        "firefox": "firefox.desktop",
        "helium": "helium.desktop",
        "librewolf": "librewolf.desktop",
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
    
    user_apps_dir = os.path.join(home_dir, ".local", "share", "applications")
    os.makedirs(user_apps_dir, exist_ok=True)
    local_dir = os.path.join(home_dir, ".local")
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(local_dir)}")
    
    config_dir = os.path.join(home_dir, ".config")
    os.makedirs(config_dir, exist_ok=True)
    
    mimeapps_content = f"""[Default Applications]
x-scheme-handler/http={desktop_file}
x-scheme-handler/https={desktop_file}
text/html={desktop_file}
application/xhtml+xml={desktop_file}
"""
    
    with open(mimeapps_path, "w") as f:
        f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(config_dir)}")
    
    run(f"xdg-mime default {desktop_file} x-scheme-handler/http", check=False)
    run(f"xdg-mime default {desktop_file} x-scheme-handler/https", check=False)
    
    print(f"  ✓ Default browser set to {config.browser.capitalize()}")
