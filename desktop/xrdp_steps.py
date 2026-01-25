"""Desktop and workstation setup steps."""

from __future__ import annotations
import os
import shlex

from lib.config import SetupConfig
from lib.machine_state import has_gpu_access, is_container
from lib.remote_utils import run


FLATPAK_REMOTE = "flathub"


def _generate_sesman_ini(config: SetupConfig, cleanup_script_path: str) -> str:
    """Generate complete sesman.ini content.
    
    Uses Xorg+xorgxrdp backend exclusively for proper dynamic resolution support.
    Xvnc is NOT included because it doesn't emit RANDR events, causing desktop
    freezes when the RDP window is resized.
    
    Xorg+xorgxrdp works in unprivileged LXC containers (no GPU access needed).
    """
    
    # Only Xorg backend - Xvnc disabled due to resize issues
    # Xorg+xorgxrdp: proper RANDR events, dynamic resize works correctly
    # Xvnc: doesn't emit RRScreenChangeNotify -> desktop freezes on resize
    return f'''[Globals]
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
EndSessionCommand={cleanup_script_path}

[Logging]
LogFile=/var/log/xrdp-sesman.log
LogLevel=INFO
EnableSyslog=true
SyslogLevel=INFO

[Xorg]
param=/usr/lib/xorg/Xorg
param=-config
param=xrdp/xorg.conf
param=-noreset
param=-nolisten
param=tcp
param=-logfile
param=.xorgxrdp.%s.log

[SessionVariables]
PULSE_SCRIPT=/etc/xrdp/pulse/default.pa
'''


def install_xrdp(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    xsession_path = f"/home/{config.username}/startwm.sh"
    cleanup_script_path = "/opt/infra_tools/desktop/service_tools/xrdp_session_cleanup.py"
    sesman_config = "/etc/xrdp/sesman.ini"
    xrdp_config = "/etc/xrdp/xrdp.ini"
    
    if config.desktop == "xfce":
        session_cmd = "xfce4-session"
    elif config.desktop == "i3":
        session_cmd = "i3"
    elif config.desktop == "cinnamon":
        session_cmd = "cinnamon-session"
    else:
        session_cmd = "xfce4-session"
    
    run("apt-get install -y -qq xrdp xorgxrdp dbus-x11 x11-xserver-utils x11-utils")
    print("  ✓ xRDP packages installed (Xorg+xorgxrdp backend for dynamic resolution)")

    # Ensure xrdp can create its runtime dirs/sockets
    run("systemctl enable xrdp-sesman", check=False)
    
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    
    # Xorg requires proper user group access for desktop session
    if has_gpu_access():
        run(f"getent group video && usermod -aG video {safe_username}", check=False)
        run(f"getent group render && usermod -aG render {safe_username}", check=False)
        print("  ✓ User added to video/render groups")
    
    # Generate sesman.ini with Xorg backend only
    if os.path.exists(sesman_config) and not os.path.exists(f"{sesman_config}.bak"):
        run(f"cp {sesman_config} {sesman_config}.bak")
    
    # Generate sesman.ini based on machine type
    try:
        sesman_content = _generate_sesman_ini(config, cleanup_script_path)
        with open(sesman_config, "w") as f:
            f.write(sesman_content)
        print("  ✓ Session manager configuration deployed")
    except Exception as e:
        print(f"  ⚠ Error deploying sesman.ini: {e}")
        return
    
    run("systemctl restart xrdp-sesman", check=False)
    
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
    
    # Configure xorgxrdp for container environments if needed
    xorg_conf_path = "/etc/X11/xrdp/xorg.conf"
    if is_container() and not os.path.exists(xorg_conf_path):
        xorg_conf_dir = os.path.dirname(xorg_conf_path)
        os.makedirs(xorg_conf_dir, exist_ok=True)
        
        xorg_conf_content = '''Section "ServerLayout"
    Identifier "X11 Server"
    Screen "Screen (xrdpdev)"
    InputDevice "xrdpMouse" "CorePointer"
    InputDevice "xrdpKeyboard" "CoreKeyboard"
EndSection

Section "ServerFlags"
    Option "DontVTSwitch" "on"
    Option "AutoAddDevices" "off"
    Option "AutoAddGPU" "off"
EndSection

Section "Module"
    Load "xorgxrdp"
    Load "fb"
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
EndSection

Section "Screen"
    Identifier "Screen (xrdpdev)"
    Device "Video Card (xrdpdev)"
    Monitor "Monitor"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
    EndSubSection
EndSection
'''
        with open(xorg_conf_path, "w") as f:
            f.write(xorg_conf_content)
        print("  ✓ xorgxrdp configuration created for container")
    
    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

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

    print("  ✓ xRDP configured with session cleanup")


def harden_xrdp(config: SetupConfig) -> None:
    """Harden xRDP with TLS encryption and group restrictions.
    
    Note: Security settings are already configured in xrdp.ini and sesman.ini templates.
    This function ensures the xrdp user has proper permissions and restarts services.
    """
    xrdp_config = "/etc/xrdp/xrdp.ini"
    
    if not os.path.exists(xrdp_config):
        print("  ⚠ xRDP not installed, skipping hardening")
        return
    
    # Ensure xrdp user has access to SSL certificates
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    
    run("systemctl restart xrdp")
    run("systemctl restart xrdp-sesman", check=False)
    
    print("  ✓ xRDP hardened (TLS encryption, strong ciphers, group restrictions)")


def configure_audio(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    home_dir = f"/home/{config.username}"
    pulse_dir = f"{home_dir}/.config/pulse"
    client_conf = f"{pulse_dir}/client.conf"
    daemon_conf = f"{pulse_dir}/daemon.conf"
    default_pa = f"{pulse_dir}/default.pa"
    
    run("apt-get install -y -qq pulseaudio pulseaudio-utils")
    
    result = run("find /usr/lib -name 'module-xrdp-sink.so' 2>/dev/null", check=False)
    modules_installed = result.returncode == 0 and bool(result.stdout.strip())
    
    configs_exist = os.path.exists(client_conf) and os.path.exists(daemon_conf)
    
    if modules_installed and configs_exist:
        print("  ✓ Audio already configured")
        return
    
    if not modules_installed:
        run("apt-get install -y -qq build-essential dpkg-dev libpulse-dev git autoconf libtool", check=False)
        
        pulse_ver_result = run("pulseaudio --version | grep -oP 'pulseaudio \\K[0-9]+\\.[0-9]+' | head -1", check=False)
        pulse_version = pulse_ver_result.stdout.strip() if pulse_ver_result.returncode == 0 else ""
        
        if pulse_version:
            print(f"  PulseAudio version: {pulse_version}")
            pulse_src_dir = f"/tmp/pulseaudio-{pulse_version}"
            if not os.path.exists(pulse_src_dir):
                run(f"apt-get source pulseaudio={pulse_version}* 2>/dev/null || apt-get source pulseaudio 2>/dev/null", check=False, cwd="/tmp")
                find_result = run("find /tmp -maxdepth 1 -type d -name 'pulseaudio-*' ! -name '*xrdp*' 2>/dev/null | head -1", check=False)
                if find_result.returncode == 0 and find_result.stdout.strip():
                    pulse_src_dir = find_result.stdout.strip()
        else:
            pulse_src_dir = None
        
        module_dir = "/tmp/pulseaudio-module-xrdp"
        if os.path.exists(module_dir):
            run(f"rm -rf {module_dir}", check=False)
        
        result = run(f"git clone https://github.com/neutrinolabs/pulseaudio-module-xrdp.git {module_dir}", check=False)
        if result.returncode != 0:
            print("  ⚠ Warning: Failed to clone pulseaudio-module-xrdp repository")
            modules_installed = False
        else:
            bootstrap_result = run(f"cd {module_dir} && ./bootstrap", check=False)
            if bootstrap_result.returncode != 0:
                print("  ⚠ Warning: Failed to bootstrap xRDP audio module")
                run(f"rm -rf {module_dir}", check=False)
                modules_installed = False
            else:
                if pulse_src_dir and os.path.exists(pulse_src_dir):
                    configure_cmd = f"cd {module_dir} && PULSE_DIR={shlex.quote(pulse_src_dir)} ./configure PULSE_DIR={shlex.quote(pulse_src_dir)}"
                    print(f"  Using PulseAudio source: {pulse_src_dir}")
                else:
                    configure_cmd = f"cd {module_dir} && PULSE_DIR=/usr ./configure PULSE_DIR=/usr"
                    print("  Using system PulseAudio headers")
                
                configure_result = run(configure_cmd, check=False)
                if configure_result.returncode != 0:
                    print("  ⚠ Warning: Failed to configure xRDP audio module")
                    run(f"rm -rf {module_dir}", check=False)
                    modules_installed = False
                else:
                    make_result = run(f"cd {module_dir} && make", check=False)
                    if make_result.returncode != 0:
                        print("  ⚠ Warning: Failed to compile xRDP audio module")
                        run(f"rm -rf {module_dir}", check=False)
                        modules_installed = False
                    else:
                        install_result = run(f"cd {module_dir} && make install", check=False)
                        if install_result.returncode != 0:
                            print("  ⚠ Warning: Failed to install xRDP audio module")
                            modules_installed = False
                        else:
                            modules_installed = True
    
    result = run("find /usr/lib -name 'module-xrdp-sink.so' 2>/dev/null", check=False)
    if result.returncode == 0 and bool(result.stdout.strip()):
        module_path = result.stdout.strip().split('\n')[0]
        print(f"  ✓ xRDP audio module installed: {module_path}")
        modules_installed = True
    else:
        print("  ⚠ xRDP audio modules not found - audio will work but not over RDP")
        modules_installed = False
    
    run(f"usermod -aG audio {safe_username}", check=False)
    
    os.makedirs(pulse_dir, exist_ok=True)
    
    with open(client_conf, "w") as f:
        f.write("autospawn = yes\n")
        f.write("daemon-binary = /usr/bin/pulseaudio\n")
    
    # Configure PulseAudio daemon
    # Containers need SHM disabled; VMs/hardware can use it for better performance
    with open(daemon_conf, "w") as f:
        if is_container():
            f.write("# Container mode: disable shared memory (not available)\n")
            f.write("enable-shm = no\n")
        else:
            f.write("# VM/hardware mode: enable shared memory for better performance\n")
            f.write("enable-shm = yes\n")
        f.write("exit-idle-time = -1\n")
        f.write("flat-volumes = no\n")
        f.write("default-sample-rate = 44100\n")
        f.write("resample-method = speex-float-1\n")
    
    if modules_installed:
        with open(default_pa, "w") as f:
            f.write("#!/usr/bin/pulseaudio -nF\n\n")
            f.write(".include /etc/pulse/default.pa\n\n")
            f.write("# Load xRDP modules for remote audio\n")
            f.write(".nofail\n")
            f.write("load-module module-xrdp-sink\n")
            f.write("load-module module-xrdp-source\n")
            f.write(".fail\n")
        run(f"chmod +x {shlex.quote(default_pa)}")
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(pulse_dir)}")
    
    troubleshoot_script = f"{home_dir}/check-rdp.sh"
    with open(troubleshoot_script, "w") as f:
        f.write("#!/bin/bash\n")
        f.write("# RDP Session Troubleshooting Script\n\n")
        f.write("echo '=== xRDP Status ==='\n")
        f.write("systemctl status xrdp --no-pager\n\n")
        f.write("echo '=== xRDP Logs (last 50 lines) ==='\n")
        f.write("journalctl -u xrdp -n 50 --no-pager\n\n")
        f.write("echo '=== Session Manager Config ==='\n")
        f.write("grep -A 5 '\\[Sessions\\]' /etc/xrdp/sesman.ini 2>/dev/null || echo 'No Sessions config'\n\n")
        f.write("echo '=== Session Cleanup Script ==='\n")
        f.write("ls -lh /opt/infra_tools/desktop/service_tools/xrdp_session_cleanup.py 2>/dev/null || echo 'Cleanup script not found'\n\n")
        f.write("echo '=== Active Sessions ==='\n")
        f.write("who\n\n")
        f.write("echo '=== User Processes ==='\n")
        f.write("ps aux | grep -E '(xrdp|$USER)' | grep -v grep\n\n")
        f.write("echo '=== Session Logs ==='\n")
        f.write("tail -50 ~/.xsession-errors 2>/dev/null || echo 'No .xsession-errors file'\n\n")
        f.write("echo '=== PulseAudio Status ==='\n")
        f.write("pactl info 2>&1 || echo 'PulseAudio not running'\n\n")
        f.write("echo '=== PulseAudio Modules ==='\n")
        f.write("pactl list modules short 2>&1 || echo 'Cannot list modules'\n\n")
        f.write("echo '=== xRDP Audio Module ==='\n")
        f.write("find /usr/lib -name 'module-xrdp-*.so' 2>/dev/null || echo 'No xRDP modules found'\n")
    run(f"chmod +x {shlex.quote(troubleshoot_script)}")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(troubleshoot_script)}")
    
    run(f"pkill -u {safe_username} pulseaudio", check=False)
    run("systemctl restart xrdp", check=False)
    
    print("  ✓ Audio configured (PulseAudio + xRDP modules)")
    print(f"  Run ~/check-rdp.sh via SSH to troubleshoot RDP issues")
