"""Desktop environment setup steps."""

from __future__ import annotations
import os
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, file_contains


def install_desktop(config: SetupConfig) -> None:
    """Install a desktop environment (XFCE, i3, or Cinnamon)."""
    if config.desktop == "xfce":
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    elif config.desktop == "i3":
        package = "i3"
        install_cmd = "apt-get install -y -qq i3 i3status i3lock dmenu"
    elif config.desktop == "cinnamon":
        package = "cinnamon"
        install_cmd = "apt-get install -y -qq cinnamon cinnamon-core"
    else:
        print(f"  ⚠ Unknown desktop environment: {config.desktop}, defaulting to XFCE")
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    
    if is_package_installed(package):
        print(f"  ✓ {config.desktop.upper()} desktop already installed")
        return
    
    run(install_cmd)
    print(f"  ✓ {config.desktop.upper()} desktop installed")


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


def install_smbclient(config: SetupConfig) -> None:
    """Install SMB/CIFS client packages for accessing network shares.
    
    Installs packages needed for file managers (like Thunar for XFCE) to 
    connect to SMB/Samba shares. Includes:
    - cifs-utils: Core SMB/CIFS mounting utilities
    - smbclient: Command-line SMB client
    - gvfs-backends: GNOME VFS backends for file manager integration
    """
    packages = ["cifs-utils", "smbclient", "gvfs-backends"]
    
    all_installed = all(is_package_installed(pkg) for pkg in packages)
    if all_installed:
        print("  ✓ SMB client packages already installed")
        return
    
    packages_str = " ".join(packages)
    run(f"apt-get install -y -qq {packages_str}")
    
    print("  ✓ SMB client packages installed (cifs-utils, smbclient, gvfs-backends)")
    print("    File managers can now browse and mount SMB/Samba shares")
