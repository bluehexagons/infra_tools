"""Desktop environment setup steps."""

from __future__ import annotations
import os
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, file_contains


def install_desktop(config: SetupConfig) -> None:
    """Install a desktop environment (XFCE, i3, Cinnamon, or LXQt)."""
    if config.desktop == "xfce":
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    elif config.desktop == "i3":
        package = "i3"
        install_cmd = "apt-get install -y -qq i3 i3status i3lock dmenu"
    elif config.desktop == "cinnamon":
        package = "cinnamon"
        install_cmd = "apt-get install -y -qq cinnamon cinnamon-core"
    elif config.desktop == "lxqt":
        package = "lxqt-core"
        install_cmd = "apt-get install -y -qq lxqt-core lxqt-config lxqt-session sddm"
    else:
        print(f"  ⚠ Unknown desktop environment: {config.desktop}, defaulting to XFCE")
        package = "xfce4"
        install_cmd = "apt-get install -y -qq xfce4 xfce4-goodies"
    
    if is_package_installed(package):
        print(f"  ✓ {config.desktop.upper()} desktop already installed")
        return
    
    run(install_cmd)
    print(f"  ✓ {config.desktop.upper()} desktop installed")


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


def configure_dark_theme(config: SetupConfig) -> None:
    """Configure desktop environment to use dark theme.
    
    Configures dark theme settings for supported desktop environments:
    - XFCE: Sets appearance and window manager themes
    - LXQt: Sets Qt theme to dark
    - Cinnamon: Sets GTK and window manager themes
    - i3: Informational message (requires manual configuration)
    """
    if not config.dark_theme:
        return
    
    safe_username = shlex.quote(config.username)
    home_dir = f"/home/{config.username}"
    
    if config.desktop == "xfce":
        xfce_config_dir = f"{home_dir}/.config/xfce4/xfconf/xfce-perchannel-xml"
        os.makedirs(xfce_config_dir, exist_ok=True)
        
        # Configure XFCE appearance settings
        xsettings_config = f"{xfce_config_dir}/xsettings.xml"
        xsettings_xml = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Net" type="empty">
    <property name="ThemeName" type="string" value="Adwaita-dark"/>
    <property name="IconThemeName" type="string" value="Adwaita"/>
  </property>
</channel>
"""
        with open(xsettings_config, "w") as f:
            f.write(xsettings_xml)
        
        # Configure XFCE window manager theme
        xfwm4_config = f"{xfce_config_dir}/xfwm4.xml"
        xfwm4_xml = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="theme" type="string" value="Default-xhdpi"/>
  </property>
</channel>
"""
        with open(xfwm4_config, "w") as f:
            f.write(xfwm4_xml)
        
        run(f"chown -R {safe_username}:{safe_username} {shlex.quote(xfce_config_dir)}")
        print("  ✓ XFCE configured with dark theme (Adwaita-dark)")
        
    elif config.desktop == "lxqt":
        lxqt_config_dir = f"{home_dir}/.config/lxqt"
        os.makedirs(lxqt_config_dir, exist_ok=True)
        
        # Configure LXQt to use dark theme
        lxqt_config_file = f"{lxqt_config_dir}/lxqt.conf"
        lxqt_config = """[General]
theme=kvantum-dark
icon_theme=breeze-dark

[Qt]
style=kvantum-dark
"""
        with open(lxqt_config_file, "w") as f:
            f.write(lxqt_config)
        
        run(f"chown -R {safe_username}:{safe_username} {shlex.quote(lxqt_config_dir)}")
        print("  ✓ LXQt configured with dark theme")
        print("    Note: Install kvantum theme packages for best results")
        
    elif config.desktop == "cinnamon":
        # Configure Cinnamon dark theme using gsettings in a single dbus session
        gsettings_script = f"""
sudo -u {safe_username} sh -c 'eval $(dbus-launch --sh-syntax) && \\
gsettings set org.cinnamon.desktop.interface gtk-theme "Adwaita-dark" && \\
gsettings set org.cinnamon.desktop.wm.preferences theme "Adwaita-dark" && \\
gsettings set org.cinnamon.theme name "Adwaita-dark"'
"""
        run(gsettings_script, check=False)
        print("  ✓ Cinnamon configured with dark theme (Adwaita-dark)")
        
    elif config.desktop == "i3":
        print("  ℹ i3 window manager detected")
        print("    Dark theme configuration requires manual i3 config file editing")
        print("    Edit ~/.config/i3/config to customize colors")
    
    else:
        print(f"  ℹ Dark theme configuration not implemented for {config.desktop}")
