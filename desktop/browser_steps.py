"""Desktop and workstation setup steps."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from typing import Optional

from lib.config import SetupConfig
from lib.machine_state import is_container
from lib.remote_utils import (
    file_contains,
    get_user_home,
    is_dry_run,
    is_package_installed,
    run,
)
from lib.release_management import fetch_latest_github_release_asset


FLATPAK_REMOTE = "flathub"
_apt_update_done = False
HELIUM_RELEASE_API = "https://api.github.com/repos/imputnet/helium-linux/releases/latest"
BROWSH_GITHUB_REPO = "browsh-org/browsh"
_LIBREWOLF_APPARMOR_PROFILE = "/etc/apparmor.d/librewolf"
_XFCE_HELPER_SUBDIR = os.path.join(".local", "share", "xfce4", "helpers")
_LIBREWOLF_PROFILE_HEADER = re.compile(
    # The package path uses AppArmor brace expansion, so match through the
    # final opening brace instead of stopping at the first path brace.
    r"(?m)^profile\s+librewolf\s+.*\s+\{$"
)
_BROWSH_ARCH_BY_DPKG = {
    "amd64": "amd64",
    "arm64": "arm64",
    "armel": "armv6",
    "armhf": "armv7",
    "i386": "386",
}


_FLATPAK_BROWSER_IDS = {
    "brave": "com.brave.Browser",
    "firefox": "org.mozilla.firefox",
    "librewolf": "io.gitlab.librewolf-community",
}


def _reload_librewolf_apparmor_profile() -> None:
    """Load LibreWolf's package-declared AppArmor profile after installation.

    The current package uses ``flags=(unconfined)`` so the browser keeps its
    own sandbox. Remove the previously loaded instance first: older
    infra-tools versions forced every profile into enforce mode, and a normal
    replacement can retain that stale runtime mode. The subsequent load still
    takes its mode from the package profile, so a future package can declare a
    different policy without being overridden.
    """
    if not os.path.isfile(_LIBREWOLF_APPARMOR_PROFILE):
        return
    if run("aa-enabled -q", check=False).returncode != 0:
        return

    try:
        with open(_LIBREWOLF_APPARMOR_PROFILE, "r", encoding="utf-8") as f:
            profile_content = f.read()
    except OSError:
        profile_content = ""

    # Some LibreWolf repository releases shipped the intended unconfined stub
    # without the required profile flag. That turns the otherwise-empty stub
    # into an enforcing allowlist and blocks the dynamic loader before the
    # browser can start. Repair only that recognizable stub; never weaken a
    # profile containing real path or capability rules.
    header_match = _LIBREWOLF_PROFILE_HEADER.search(profile_content)
    if (
        header_match
        and "flags=" not in header_match.group(0)
        and "userns," in profile_content
        and "include if exists <local/librewolf>" in profile_content
        and not re.search(r"(?m)^\s*(?:deny\s+|/|owner\s+)", profile_content)
    ):
        repaired_header = header_match.group(0)[:-1].rstrip() + " flags=(unconfined) {"
        repaired_content = (
            profile_content[: header_match.start()]
            + repaired_header
            + profile_content[header_match.end() :]
        )
        try:
            with open(_LIBREWOLF_APPARMOR_PROFILE, "w", encoding="utf-8") as f:
                f.write(repaired_content)
            print("  ✓ Repaired LibreWolf's malformed AppArmor compatibility profile")
        except OSError:
            print("  ⚠ Could not repair LibreWolf's AppArmor compatibility profile")

    run(
        f"apparmor_parser -R {shlex.quote(_LIBREWOLF_APPARMOR_PROFILE)}",
        check=False,
    )
    result = run(
        f"apparmor_parser -r -W {shlex.quote(_LIBREWOLF_APPARMOR_PROFILE)}",
        check=False,
    )
    if result.returncode != 0:
        print("  ⚠ Could not reload LibreWolf's unconfined AppArmor profile")


def _browsh_architecture() -> str:
    """Return the Browsh release architecture for the target Debian system."""
    result = run("dpkg --print-architecture", check=False, capture_output=True)
    dpkg_arch = (result.stdout or "").strip()
    try:
        return _BROWSH_ARCH_BY_DPKG[dpkg_arch]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported Browsh architecture: {dpkg_arch or 'unknown'}") from exc


def _browsh_asset_matches(tag_name: str, asset_name: str, arch: str) -> bool:
    """Return whether a release asset is the Debian package for ``arch``."""
    version = tag_name.removeprefix("v")
    return asset_name == f"browsh_{version}_linux_{arch}.deb"


def _resolve_browsh_deb() -> tuple[str, str]:
    """Return the newest stable Browsh release with a matching Debian asset."""
    arch = _browsh_architecture()
    return fetch_latest_github_release_asset(
        BROWSH_GITHUB_REPO,
        asset_matches=lambda tag_name, asset_name: _browsh_asset_matches(
            tag_name, asset_name, arch
        ),
        missing_asset_description=(
            f"No stable Browsh Debian package found for architecture '{arch}'"
        ),
    )


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
                _reload_librewolf_apparmor_profile()
                print("  ✓ LibreWolf browser already installed")
                return
            print("  Installing LibreWolf browser...")

            if _install_via_extrepo("LibreWolf", "librewolf", "librewolf"):
                _reload_librewolf_apparmor_profile()
                print("  ✓ LibreWolf browser installed")

    elif browser == "helium":
        _install_helium_browser()
    
    elif browser == "browsh":
        if is_package_installed("browsh") or shutil.which("browsh"):
            print("  ✓ Browsh already installed")
            return

        print("  Installing Browsh (requires Firefox)...")
        if not (is_package_installed("firefox") or is_package_installed("firefox-esr")):
            print("  Installing Firefox (required for Browsh)...")
            run("apt-get install -y -qq firefox-esr", check=False)
        
        try:
            tag_name, browsh_url = _resolve_browsh_deb()
        except RuntimeError as exc:
            print(f"  ✗ Failed to resolve current Browsh release: {exc}")
            return
        run(
            f"wget -qO /tmp/browsh.deb {shlex.quote(browsh_url)}",
            check=False,
            display_cmd=f"wget -qO /tmp/browsh.deb <Browsh {tag_name} release URL>",
        )
        run("apt-get install -y -qq /tmp/browsh.deb", check=False)
        run("rm -f /tmp/browsh.deb", check=False)
        if is_package_installed("browsh") or shutil.which("browsh"):
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

    flatpak_app_id = _FLATPAK_BROWSER_IDS.get(config.browser)
    using_flatpak_browser = bool(
        config.use_flatpak
        and flatpak_app_id
        and is_flatpak_app_installed(flatpak_app_id)
    )
    if using_flatpak_browser:
        desktop_file = f"{flatpak_app_id}.desktop"
    
    mimeapps_already_configured = os.path.exists(mimeapps_path) and file_contains(
        mimeapps_path, desktop_file
    )
    
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

    if not mimeapps_already_configured:
        with open(mimeapps_path, "w", encoding="utf-8") as f:
            f.write(mimeapps_content)
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(config_dir)}")
    
    browser_command = {
        "brave": "brave-browser",
        "firefox": "firefox",
        "helium": "helium",
        "librewolf": "librewolf",
    }[config.browser]
    if using_flatpak_browser:
        browser_command = f"flatpak run {flatpak_app_id}"

    helper_dir = os.path.join(home_dir, _XFCE_HELPER_SUBDIR)
    os.makedirs(helper_dir, exist_ok=True)
    helper_path = os.path.join(helper_dir, f"{config.browser}.desktop")
    if using_flatpak_browser:
        helper_binaries = "flatpak;"
        helper_commands = browser_command
        helper_commands_with_parameter = f'{browser_command} "%s"'
    else:
        helper_binaries = f"{browser_command};"
        helper_commands = "%B"
        helper_commands_with_parameter = '%B "%s"'
    helper_content = f"""[Desktop Entry]
Version=1.0
Type=X-XFCE-Helper
Name={config.browser.capitalize()}
StartupNotify=true
X-XFCE-Binaries={helper_binaries}
X-XFCE-Category=WebBrowser
X-XFCE-Commands={helper_commands};
X-XFCE-CommandsWithParameter={helper_commands_with_parameter};
"""
    try:
        with open(helper_path, "r", encoding="utf-8") as f:
            existing_helper = f.read()
    except OSError:
        existing_helper = ""
    if existing_helper != helper_content:
        with open(helper_path, "w", encoding="utf-8") as f:
            f.write(helper_content)

    xfce_config_dir = os.path.join(config_dir, "xfce4")
    os.makedirs(xfce_config_dir, exist_ok=True)
    xfce_helpers_path = os.path.join(xfce_config_dir, "helpers.rc")
    existing_helpers = ""
    if os.path.exists(xfce_helpers_path):
        try:
            with open(xfce_helpers_path, "r", encoding="utf-8") as f:
                existing_helpers = f.read()
        except OSError:
            existing_helpers = ""
    helper_lines = [
        line for line in existing_helpers.splitlines()
        if not line.startswith("WebBrowser=")
    ]
    helper_lines.append(f"WebBrowser={browser_command}")
    helpers_content = "\n".join(helper_lines) + "\n"
    if existing_helpers != helpers_content:
        with open(xfce_helpers_path, "w", encoding="utf-8") as f:
            f.write(helpers_content)

    user_env = (
        f"runuser -u {safe_username} -- env"
        f" HOME={shlex.quote(home_dir)}"
        f" XDG_CONFIG_HOME={shlex.quote(config_dir)}"
    )
    for mime_type in (
        "x-scheme-handler/http",
        "x-scheme-handler/https",
        "text/html",
        "application/xhtml+xml",
    ):
        run(
            f"{user_env} xdg-mime default {desktop_file} {mime_type}",
            check=False,
        )
    run(f"{user_env} xdg-settings set default-web-browser {desktop_file}", check=False)
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(local_dir)}")
    
    print(f"  ✓ Default browser set to {config.browser.capitalize()}")
