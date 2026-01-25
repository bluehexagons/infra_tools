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


def configure_xfce_for_rdp(config: SetupConfig) -> None:
    """Configure XFCE to work properly in RDP sessions.
    
    Fixes common issues:
    - Disables light-locker (crashes without display manager)
    - Disables xfce4-power-manager display features (no DPMS in RDP)
    - Creates stub pm-is-supported to suppress warnings
    - Removes problematic autostart entries
    """
    if config.desktop != "xfce":
        return
    
    safe_username = shlex.quote(config.username)
    home_dir = f"/home/{config.username}"
    autostart_dir = f"{home_dir}/.config/autostart"
    xfce_config_dir = f"{home_dir}/.config/xfce4/xfconf/xfce-perchannel-xml"
    
    # Create autostart directory
    os.makedirs(autostart_dir, exist_ok=True)
    
    # 1. Disable light-locker (crashes in RDP sessions without display manager)
    light_locker_desktop = f"{autostart_dir}/light-locker.desktop"
    with open(light_locker_desktop, "w") as f:
        f.write("""[Desktop Entry]
Type=Application
Name=Light Locker
Comment=Screen Locker (disabled for RDP)
Hidden=true
""")
    
    # 2. Create stub pm-is-supported to suppress xfce4-session warnings
    pm_stub = "/usr/local/bin/pm-is-supported"
    if not os.path.exists(pm_stub):
        with open(pm_stub, "w") as f:
            f.write("""#!/bin/bash
# Stub for pm-is-supported to suppress XFCE warnings in containers/RDP
# Always returns false (1) - no power management available
exit 1
""")
        run(f"chmod +x {shlex.quote(pm_stub)}")
    
    # 3. Remove invalid XKBOPTIONS autostart entry if it exists
    swap_escape_desktop = f"{autostart_dir}/swap escape.desktop"
    if os.path.exists(swap_escape_desktop):
        os.remove(swap_escape_desktop)
    
    # 4. Configure xfce4-power-manager to not manage displays
    os.makedirs(xfce_config_dir, exist_ok=True)
    power_manager_config = f"{xfce_config_dir}/xfce4-power-manager.xml"
    
    power_manager_xml = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="dpms-on-ac-sleep" type="uint" value="0"/>
    <property name="dpms-on-ac-off" type="uint" value="0"/>
    <property name="dpms-on-battery-sleep" type="uint" value="0"/>
    <property name="dpms-on-battery-off" type="uint" value="0"/>
    <property name="brightness-switch-restore-on-exit" type="int" value="-1"/>
    <property name="brightness-switch" type="int" value="0"/>
    <property name="handle-brightness-keys" type="bool" value="false"/>
  </property>
</channel>
"""
    with open(power_manager_config, "w") as f:
        f.write(power_manager_xml)
    
    # 5. Configure xfsettingsd to not manage displays (prevents "Failed to apply display settings")
    xfsettingsd_config = f"{xfce_config_dir}/displays.xml"
    displays_xml = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="displays" version="1.0">
  <property name="Default" type="empty">
    <property name="HDMI-1" type="string" value="Laptop">
      <property name="Active" type="bool" value="true"/>
      <property name="Resolution" type="string" value=""/>
      <property name="RefreshRate" type="double" value="0"/>
      <property name="Rotation" type="int" value="0"/>
      <property name="Reflection" type="string" value="0"/>
      <property name="Primary" type="bool" value="false"/>
      <property name="Position" type="empty">
        <property name="X" type="int" value="0"/>
        <property name="Y" type="int" value="0"/>
      </property>
    </property>
  </property>
</channel>
"""
    with open(xfsettingsd_config, "w") as f:
        f.write(displays_xml)
    
    # Set ownership
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(autostart_dir)}")
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(xfce_config_dir)}")
    
    print("  ✓ XFCE configured for RDP compatibility")
    print("    - light-locker disabled (prevents crashes)")
    print("    - Display power management disabled (no DPMS in RDP)")
    print("    - Power management warnings suppressed")


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
