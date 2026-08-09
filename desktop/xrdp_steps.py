"""Desktop and workstation setup steps."""

from __future__ import annotations
import os
import shlex

from lib.config import SetupConfig
from lib.machine_state import has_gpu_access
from lib.remote_utils import is_service_active, run, is_package_installed


def _generate_sesman_ini() -> str:
    """Generate complete sesman.ini content.
    
    Uses Xorg+xorgxrdp backend exclusively for the most stable resize behaviour.
    Xvnc is NOT included because it doesn't emit RANDR events, causing desktop
    freezes when the RDP window is resized.

    This path is tuned for VM-first desktops while still providing best-effort
    compatibility for headless/container guests.
    """
    
    # Only Xorg backend - Xvnc disabled due to resize issues
    # Xorg+xorgxrdp: proper RANDR events, dynamic resize works correctly
    # Xvnc: doesn't emit RRScreenChangeNotify -> desktop freezes on resize
    return '''[Globals]
EnableUserWindowManager=true
UserWindowManager=startwm.sh
DefaultWindowManager=startwm.sh
ReconnectScript=/bin/true

[Security]
AllowRootLogin=false
MaxLoginRetry=3
TerminalServerUsers=remoteusers
AlwaysGroupCheck=true

[Sessions]
X11DisplayOffset=10
MaxSessions=10
Policy=Default

[Logging]
LogFile=/var/log/xrdp-sesman.log
LogLevel=INFO
EnableSyslog=true
SyslogLevel=INFO

[Xorg]
param=/usr/lib/xorg/Xorg
param=-config
param=/etc/X11/xrdp/xorg.conf
param=-noreset
param=-nolisten
param=tcp
param=-logfile
param=.xorgxrdp.%s.log
'''


def _generate_xorg_conf() -> str:
    """Generate the managed xorgxrdp configuration."""
    return '''Section "ServerLayout"
    Identifier "X11 Server"
    Screen "Screen (xrdpdev)"
    InputDevice "xrdpMouse" "CorePointer"
    InputDevice "xrdpKeyboard" "CoreKeyboard"
EndSection

Section "ServerFlags"
    Option "DontVTSwitch" "on"
    Option "AutoAddDevices" "off"
    Option "AutoAddGPU" "off"
    # Disable screen saver and DPMS to prevent display management conflicts
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
    Option "BlankTime" "0"
EndSection

Section "Module"
    Load "fb"
    Load "glamoregl"
    Load "xorgxrdp"
EndSection

Section "InputDevice"
    Identifier "xrdpKeyboard"
    Driver "xrdpkeyb"
EndSection

Section "InputDevice"
    Identifier "xrdpMouse"
    Driver "xrdpmouse"
EndSection

Section "Monitor"
    Identifier "Monitor"
    HorizSync 30-80
    VertRefresh 50-75
EndSection

Section "Device"
    Identifier "Video Card (xrdpdev)"
    Driver "xrdpdev"
    # Disable glamor acceleration for the most stable XRDP resize behaviour
    Option "UseGlamor" "false"
    # Software cursor prevents cursor-related resize issues
    Option "SWCursor" "true"
EndSection

Section "Screen"
    Identifier "Screen (xrdpdev)"
    Device "Video Card (xrdpdev)"
    Monitor "Monitor"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        # Virtual screen size to support dynamic resizing (up to 4K: 3840x2160)
        # Supports 4K and common ultrawide resolutions
        Virtual 3840 2160
    EndSubSection
EndSection
'''


def _ensure_user_in_group(username: str, group: str) -> bool:
    """Ensure the given user is a member of the given group."""
    quoted_username = shlex.quote(username)
    quoted_group = shlex.quote(group)
    membership_check_cmd = f"id -nG {quoted_username} | tr ' ' '\\n' | grep -Fxq {quoted_group}"
    membership_check = run(membership_check_cmd, check=False)
    if membership_check.returncode == 0:
        return False

    add_result = run(
        f"getent group {quoted_group} && adduser {quoted_username} {quoted_group}",
        check=False,
    )
    if add_result.returncode != 0:
        print(f"  ⚠ Could not add {username} to group {group}")
        return False

    membership_check = run(membership_check_cmd, check=False)
    if membership_check.returncode != 0:
        print(f"  ⚠ Could not verify membership after adding {username} to group {group}")
        return False

    return True


def _refresh_services(*services: str, reload_running_services: bool = True) -> None:
    """Refresh active services and start inactive ones."""
    active_services = [service for service in services if is_service_active(service)]
    inactive_services = [service for service in services if service not in active_services]

    if reload_running_services and active_services:
        active_list = " ".join(shlex.quote(service) for service in active_services)
        run(f"systemctl reload-or-restart {active_list}", check=False)

    if inactive_services:
        inactive_list = " ".join(shlex.quote(service) for service in inactive_services)
        run(f"systemctl start {inactive_list}", check=False)


def install_xrdp(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    xsession_path = f"/home/{config.username}/startwm.sh"
    sesman_config = "/etc/xrdp/sesman.ini"
    xrdp_config = "/etc/xrdp/xrdp.ini"
    
    if config.desktop == "xfce":
        session_cmd = "xfce4-session"
    elif config.desktop == "i3":
        session_cmd = "i3"
    elif config.desktop == "cinnamon":
        session_cmd = "cinnamon-session"
    elif config.desktop == "lxqt":
        session_cmd = "startlxqt"
    else:
        session_cmd = "xfce4-session"
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq xrdp xorgxrdp dbus-x11 x11-xserver-utils x11-utils", check=False)
    if is_package_installed("xrdp"):
        print("  ✓ xRDP packages installed (Xorg+xorgxrdp backend for dynamic resolution)")

    # Configure Xwrapper to allow XRDP sessions to start X server
    # This is critical for preventing session freezes and startup issues
    xwrapper_config = "/etc/X11/Xwrapper.config"
    xwrapper_content = """# Xwrapper configuration for XRDP
# Allow any user to start X server (required for remote desktop sessions)
allowed_users=anybody
# Don't require root privileges
needs_root_rights=no
"""
    
    # Ensure directory exists
    xwrapper_dir = os.path.dirname(xwrapper_config)
    if not os.path.exists(xwrapper_dir):
        try:
            os.makedirs(xwrapper_dir, exist_ok=True)
        except OSError as e:
            print(f"  ⚠ ERROR: Could not create {xwrapper_dir}: {e}")
            print(f"  ⚠ XRDP may experience session startup issues without proper Xwrapper configuration")
            print(f"  ⚠ Manually create the directory and file if needed")
    
    # Backup existing Xwrapper.config before overwriting
    if os.path.exists(xwrapper_config) and not os.path.exists(f"{xwrapper_config}.bak"):
        run(f"cp {xwrapper_config} {xwrapper_config}.bak")
    
    try:
        with open(xwrapper_config, "w") as f:
            f.write(xwrapper_content)
        print("  ✓ Xwrapper configured (allows XRDP to start X server)")
    except (IOError, OSError) as e:
        print(f"  ⚠ ERROR: Could not write to {xwrapper_config}: {e}")
        print(f"  ⚠ CRITICAL: XRDP sessions may freeze or fail to start")
        print(f"  ⚠ Manual fix required:")
        print(f"      sudo mkdir -p {xwrapper_dir}")
        print(f"      echo 'allowed_users=anybody' | sudo tee {xwrapper_config}")
        print(f"      echo 'needs_root_rights=no' | sudo tee -a {xwrapper_config}")

    # Ensure xrdp can create its runtime dirs/sockets
    run("systemctl enable xrdp-sesman", check=False)
    
    _ensure_user_in_group("xrdp", "ssl-cert")
    
    # Xorg requires proper user group access for desktop session
    if has_gpu_access():
        run(f"getent group video && usermod -aG video {safe_username}", check=False)
        run(f"getent group render && usermod -aG render {safe_username}", check=False)
        print("  ✓ User added to video/render groups")
    
    # Generate sesman.ini with Xorg backend only
    if os.path.exists(sesman_config) and not os.path.exists(f"{sesman_config}.bak"):
        run(f"cp {sesman_config} {sesman_config}.bak")
    
    # Generate the managed sesman.ini.
    try:
        sesman_content = _generate_sesman_ini()
        with open(sesman_config, "w") as f:
            f.write(sesman_content)
        print("  ✓ Session manager configuration deployed")
    except Exception as e:
        print(f"  ⚠ Error deploying sesman.ini: {e}")
        return
    
    if os.path.exists(xrdp_config) and not os.path.exists(f"{xrdp_config}.bak"):
        run(f"cp {xrdp_config} {xrdp_config}.bak")
    
    # xrdp.ini doesn't need machine-type-specific changes, use template
    config_template_dir = os.path.join(os.path.dirname(__file__), 'config')
    xrdp_template_path = os.path.join(config_template_dir, 'xrdp.ini.template')
    try:
        with open(xrdp_template_path, 'r', encoding='utf-8') as f:
            xrdp_content = f.read()
        with open(xrdp_config, "w") as f:
            f.write(xrdp_content)
        print("  ✓ xRDP configuration deployed")
    except FileNotFoundError:
        print(f"  ⚠ xrdp.ini template not found: {xrdp_template_path}, using default config")
    except Exception as e:
        print(f"  ⚠ Error deploying xrdp.ini template: {e}")
    
    # Configure xorgxrdp - required for all XRDP environments
    # Fix for Debian Trixie/X.Org 21.1.16: glamoregl must be loaded before xorgxrdp
    # to resolve undefined glamor_xv_init symbol errors.
    # UseGlamor=false keeps the software-rendered path that has been the most
    # stable across VM-first desktops and compatibility guests.
    # Large virtual screen supports up to 4K+ resolutions for dynamic resizing.
    xorg_conf_path = "/etc/X11/xrdp/xorg.conf"
    xorg_conf_dir = os.path.dirname(xorg_conf_path)
    os.makedirs(xorg_conf_dir, exist_ok=True)
    if os.path.exists(xorg_conf_path) and not os.path.exists(f"{xorg_conf_path}.bak"):
        run(f"cp {xorg_conf_path} {xorg_conf_path}.bak")
    with open(xorg_conf_path, "w") as f:
        f.write(_generate_xorg_conf())
    print("  ✓ xorgxrdp configuration deployed")
    
    run("systemctl enable xrdp")
    _refresh_services("xrdp-sesman", "xrdp")

    xsession_template_path = os.path.join(config_template_dir, 'xrdp_xsession.template')
    try:
        with open(xsession_template_path, 'r', encoding='utf-8') as f:
            xsession_content = f.read()
    except FileNotFoundError:
        print(f"  ⚠ xsession template file not found: {xsession_template_path}")
        return
    except Exception as e:
        print(f"  ⚠ Error reading xsession template: {e}")
        return
    
    xsession_content = xsession_content.replace('{SESSION_CMD}', session_cmd)
    
    with open(xsession_path, "w") as f:
        f.write(xsession_content)
    run(f"chmod +x {shlex.quote(xsession_path)}")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP configured")


def harden_xrdp(config: SetupConfig) -> None:
    """Harden xRDP with TLS encryption and group restrictions.
    
    Note: Security settings are already configured in xrdp.ini and sesman.ini templates.
    This function ensures the xrdp user has proper permissions and only refreshes
    services when that access changes or the services are not running.
    """
    xrdp_config = "/etc/xrdp/xrdp.ini"
    
    if not os.path.exists(xrdp_config):
        print("  ⚠ xRDP not installed, skipping hardening")
        return
    
    # Ensure xrdp user has access to SSL certificates
    ssl_cert_changed = _ensure_user_in_group("xrdp", "ssl-cert")
    _refresh_services("xrdp-sesman", "xrdp", reload_running_services=ssl_cert_changed)
    
    print("  ✓ xRDP hardened (TLS encryption, strong ciphers, group restrictions)")
