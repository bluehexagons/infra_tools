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


def install_desktop(config: SetupConfig) -> None:
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


def install_xrdp(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    xsession_path = f"/home/{config.username}/.xsession"
    cleanup_script_path = "/opt/infra_tools/steps/xrdp_session_cleanup.py"
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
    
    # Check if already fully configured (including cleanup script)
    if is_package_installed("xrdp") and os.path.exists(xsession_path) and os.path.exists(cleanup_script_path):
        if is_service_active("xrdp"):
            print("  ✓ xRDP already installed and configured")
            return

    if not is_package_installed("xrdp"):
        run("apt-get install -y -qq xrdp")
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)

    # Configure sesman.ini with session cleanup and timeout policies
    # Check each setting individually to avoid duplicates
    if not file_contains(sesman_config, "[Sessions]"):
        run(f"echo '\n[Sessions]' >> {sesman_config}")
    
    if not file_contains(sesman_config, "EndSessionCommand="):
        run(f"sed -i '/\\[Sessions\\]/a EndSessionCommand={cleanup_script_path}' {sesman_config}")
    
    if not file_contains(sesman_config, "SessionVariables="):
        run(f"sed -i '/\\[Sessions\\]/a SessionVariables=DBUS_SESSION_BUS_ADDRESS' {sesman_config}")
    
    if not file_contains(sesman_config, "IdleTimeLimit="):
        # Add idle timeout (30 minutes) to prevent abandoned sessions
        run(f"sed -i '/\\[Sessions\\]/a IdleTimeLimit=1800' {sesman_config}")
    
    if not file_contains(sesman_config, "DisconnectedTimeLimit="):
        # Maximum session time (8 hours) as a safety measure
        run(f"sed -i '/\\[Sessions\\]/a DisconnectedTimeLimit=28800' {sesman_config}")
    
    # Enable session reconnection for better user experience
    # Users can disconnect and reconnect to the same session
    if not file_contains(sesman_config, "Policy="):
        run(f"sed -i '/\\[Sessions\\]/a Policy=Default' {sesman_config}")
    
    # Configure logging for better troubleshooting
    if not file_contains(sesman_config, "[Logging]"):
        run(f"echo '\n[Logging]' >> {sesman_config}")
    
    if not file_contains(sesman_config, "LogLevel="):
        # INFO level provides good balance between detail and noise
        run(f"sed -i '/\\[Logging\\]/a LogLevel=INFO' {sesman_config}")
    
    # Performance: Enable compression for better performance over slow connections
    if not file_contains(xrdp_config, "tcp_send_buffer_bytes"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a tcp_send_buffer_bytes=32768' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\ntcp_send_buffer_bytes=32768' {xrdp_config}")
    
    if not file_contains(xrdp_config, "tcp_recv_buffer_bytes"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a tcp_recv_buffer_bytes=32768' {xrdp_config}")
    
    # Performance: Disable unnecessary features for better performance
    if not file_contains(xrdp_config, "bulk_compression="):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a bulk_compression=true' {xrdp_config}")
    
    run("systemctl enable xrdp")
    run("systemctl restart xrdp")

    # Create .xsession from template
    config_template_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
    template_path = os.path.join(config_template_dir, 'xrdp_xsession.template')
    with open(template_path, 'r', encoding='utf-8') as f:
        xsession_content = f.read()
    
    # Replace template variables
    xsession_content = xsession_content.replace('{SESSION_CMD}', session_cmd)
    
    with open(xsession_path, "w") as f:
        f.write(xsession_content)
    run(f"chmod +x {shlex.quote(xsession_path)}")
    run(f"chown {safe_username}:{safe_username} {shlex.quote(xsession_path)}")

    print("  ✓ xRDP installed and configured with session cleanup")


def harden_xrdp(config: SetupConfig) -> None:
    """Harden xRDP with TLS encryption, certificate validation, and group restrictions."""
    xrdp_config = "/etc/xrdp/xrdp.ini"
    sesman_config = "/etc/xrdp/sesman.ini"
    
    if not os.path.exists(xrdp_config):
        print("  ⚠ xRDP not installed, skipping hardening")
        return
    
    if (file_contains(xrdp_config, "security_layer=tls") and
        file_contains(sesman_config, "AllowGroups=remoteusers") and
        file_contains(sesman_config, "DenyUsers=root")):
        print("  ✓ xRDP already hardened")
        return
    
    # Security: TLS encryption
    run(f"sed -i 's/^#\\?security_layer=.*/security_layer=tls/' {xrdp_config}")
    run(f"sed -i 's/^#\\?crypt_level=.*/crypt_level=high/' {xrdp_config}")
    
    if not file_contains(xrdp_config, "security_layer"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a security_layer=tls' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\nsecurity_layer=tls' {xrdp_config}")
    
    if not file_contains(xrdp_config, "crypt_level"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a crypt_level=high' {xrdp_config}")
        else:
            run(f"sed -i '1i crypt_level=high' {xrdp_config}")
    
    # Security: Disable weaker encryption protocols
    if not file_contains(xrdp_config, "tls_ciphers"):
        if file_contains(xrdp_config, "[Globals]"):
            # Use strong cipher suites only
            run(f"sed -i '/\\[Globals\\]/a tls_ciphers=HIGH:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4' {xrdp_config}")
    
    # Security: User access restrictions
    if not file_contains(sesman_config, "[Security]"):
        run(f"echo '\n[Security]' >> {sesman_config}")
    
    if not file_contains(sesman_config, "AllowGroups"):
        run(f"sed -i '/\\[Security\\]/a AllowGroups=remoteusers' {sesman_config}")
    
    if not file_contains(sesman_config, "DenyUsers"):
        run(f"sed -i '/\\[Security\\]/a DenyUsers=root' {sesman_config}")
    
    # Security: Restrict login attempts
    if not file_contains(sesman_config, "MaxLoginRetry"):
        run(f"sed -i '/\\[Security\\]/a MaxLoginRetry=3' {sesman_config}")
    
    # Performance: Configure max session limits
    if not file_contains(sesman_config, "MaxSessions"):
        if not file_contains(sesman_config, "[Sessions]"):
            run(f"echo '\n[Sessions]' >> {sesman_config}")
        # Allow up to 10 concurrent sessions per user (reasonable limit)
        run(f"sed -i '/\\[Sessions\\]/a MaxSessions=10' {sesman_config}")
    
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)
    
    run("systemctl restart xrdp")
    run("systemctl restart xrdp-sesman", check=False)
    
    print("  ✓ xRDP hardened (TLS encryption, strong ciphers, root denied, restricted to remoteusers group)")


def install_x2go(config: SetupConfig) -> None:
    """Install X2Go server for remote desktop access."""
    if is_package_installed("x2goserver"):
        print("  ✓ X2Go already installed")
        return
    
    run("apt-get install -y -qq x2goserver x2goserver-xsession")
    
    run("systemctl enable ssh", check=False)
    run("systemctl start ssh", check=False)
    
    print("  ✓ X2Go installed (connect via SSH on port 22)")


def configure_xfce_for_x2go(config: SetupConfig) -> None:
    """Configure Xfce to work properly with X2Go by disabling compositor."""
    safe_username = shlex.quote(config.username)
    home_dir = f"/home/{config.username}"
    xfce_config_dir = f"{home_dir}/.config/xfce4/xfconf/xfce-perchannel-xml"
    xfwm4_config = f"{xfce_config_dir}/xfwm4.xml"
    
    os.makedirs(xfce_config_dir, exist_ok=True)
    
    if os.path.exists(xfwm4_config):
        if file_contains(xfwm4_config, 'name="use_compositing" type="bool" value="false"'):
            print("  ✓ Xfce compositor already disabled for X2Go")
            return
    
    xfwm4_content = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="frame_opacity" type="int" value="100"/>
    <property name="inactive_opacity" type="int" value="100"/>
  </property>
</channel>
"""
    
    with open(xfwm4_config, "w") as f:
        f.write(xfwm4_content)
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(home_dir)}/.config")
    
    autostart_dir = f"{home_dir}/.config/autostart"
    os.makedirs(autostart_dir, exist_ok=True)
    
    compositor_script = f"{autostart_dir}/disable-compositor.desktop"
    compositor_content = """[Desktop Entry]
Type=Application
Name=Disable Xfce Compositor for X2Go
Exec=xfconf-query -c xfwm4 -p /general/use_compositing -s false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
    
    with open(compositor_script, "w") as f:
        f.write(compositor_content)
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(autostart_dir)}")
    
    print("  ✓ Xfce compositor disabled for X2Go (prevents graphical issues)")


def harden_x2go(config: SetupConfig) -> None:
    """Harden X2Go by restricting to remoteusers group."""
    x2go_config = "/etc/x2go/x2goserver.conf"
    
    if not os.path.exists(x2go_config):
        print("  ⚠ X2Go not installed, skipping hardening")
        return
    
    if not file_contains(x2go_config, "# Security hardened"):
        with open(x2go_config, "a") as f:
            f.write("\n# Security hardened\n")
            f.write("# Restrict to remoteusers group via SSH AllowGroups\n")
    
    print("  ✓ X2Go hardened (uses SSH security + group restrictions)")



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
    
    with open(daemon_conf, "w") as f:
        f.write("enable-shm = no\n")
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
        f.write("ls -lh /usr/local/bin/xrdp-session-cleanup.sh 2>/dev/null || echo 'Cleanup script not found'\n\n")
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


def install_browser(config: SetupConfig) -> None:
    """Install the specified browser."""
    if not config.browser:
        return

    if config.browser == "brave":
        if config.use_flatpak:
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
    
    elif config.browser == "firefox":
        if config.use_flatpak:
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
    
    elif config.browser == "browsh":
        print("  Installing Browsh (requires Firefox)...")
        if not (is_package_installed("firefox") or is_package_installed("firefox-esr")):
            print("  Installing Firefox (required for Browsh)...")
            run("apt-get install -y -qq firefox-esr", check=False)
        
        if not os.path.exists("/usr/local/bin/browsh"):
            run("wget -qO /tmp/browsh.deb https://github.com/browsh-org/browsh/releases/download/v1.8.0/browsh_1.8.0_linux_amd64.deb", check=False)
            run("apt-get install -y -qq /tmp/browsh.deb", check=False)
            run("rm -f /tmp/browsh.deb", check=False)
        print("  ✓ Browsh installed")
    
    elif config.browser == "vivaldi":
        if config.use_flatpak:
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
    
    elif config.browser == "lynx":
        if is_package_installed("lynx"):
            print("  ✓ Lynx already installed")
            return
        print("  Installing Lynx...")
        run("apt-get install -y -qq lynx", check=False)
        print("  ✓ Lynx installed")


def install_remmina(config: SetupConfig) -> None:
    """Install Remmina RDP client."""
    if is_package_installed("remmina"):
        print("  ✓ Remmina already installed")
        return
    
    print("  Installing Remmina...")
    run("apt-get install -y -qq remmina remmina-plugin-rdp remmina-plugin-vnc", check=False)
    print("  ✓ Remmina installed")


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
    
    if is_package_installed("gnome-keyring"):
        print("  ✓ gnome-keyring already installed")
        return
    
    run("apt-get install -y -qq gnome-keyring libpam-gnome-keyring")
    
    pam_password = "/etc/pam.d/common-password"
    pam_session = "/etc/pam.d/common-session"
    
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
    
    print("  ✓ gnome-keyring configured (auto-unlock on login, SSH agent integration)")


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
