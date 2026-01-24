"""Desktop and workstation setup steps."""

from __future__ import annotations
from typing import Optional
import os
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, is_service_active, file_contains


FLATPAK_REMOTE = "flathub"

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
    
    run("apt-get install -y -qq xrdp xorgxrdp dbus-x11")
    print("  ✓ xRDP packages installed/updated")
    
    run("getent group ssl-cert && adduser xrdp ssl-cert", check=False)

    config_template_dir = os.path.join(os.path.dirname(__file__), '..', 'desktop', 'config')
    
    if os.path.exists(sesman_config) and not os.path.exists(f"{sesman_config}.bak"):
        run(f"cp {sesman_config} {sesman_config}.bak")
    
    sesman_template_path = os.path.join(config_template_dir, 'xrdp_sesman.ini.template')
    try:
        with open(sesman_template_path, 'r', encoding='utf-8') as f:
            sesman_content = f.read()
    except FileNotFoundError:
        print(f"  ⚠ Template file not found: {sesman_template_path}")
        return
    except Exception as e:
        print(f"  ⚠ Error reading template: {e}")
        return
    
    sesman_content = sesman_content.replace('{CLEANUP_SCRIPT_PATH}', cleanup_script_path)
    
    with open(sesman_config, "w") as f:
        f.write(sesman_content)
    
    run("systemctl restart xrdp-sesman", check=False)
    
    if not file_contains(xrdp_config, "tcp_send_buffer_bytes"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a tcp_send_buffer_bytes=32768' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\ntcp_send_buffer_bytes=32768' {xrdp_config}")
    
    if not file_contains(xrdp_config, "tcp_recv_buffer_bytes"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a tcp_recv_buffer_bytes=32768' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\ntcp_recv_buffer_bytes=32768' {xrdp_config}")
    
    if not file_contains(xrdp_config, "bulk_compression="):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a bulk_compression=true' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\nbulk_compression=true' {xrdp_config}")
    
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
    """Harden xRDP with TLS encryption and group restrictions."""
    xrdp_config = "/etc/xrdp/xrdp.ini"
    sesman_config = "/etc/xrdp/sesman.ini"
    
    if not os.path.exists(xrdp_config):
        print("  ⚠ xRDP not installed, skipping hardening")
        return
    
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
    
    if not file_contains(xrdp_config, "tls_ciphers"):
        if file_contains(xrdp_config, "[Globals]"):
            run(f"sed -i '/\\[Globals\\]/a tls_ciphers=HIGH:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4' {xrdp_config}")
        else:
            run(f"sed -i '1i [Globals]\\ntls_ciphers=HIGH:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4' {xrdp_config}")
    
    if not file_contains(sesman_config, "[Security]"):
        run(f"echo '\n[Security]' >> {sesman_config}")
    
    if not file_contains(sesman_config, "AllowGroups"):
        run(f"sed -i '/\\[Security\\]/a AllowGroups=remoteusers' {sesman_config}")
    
    if not file_contains(sesman_config, "DenyUsers"):
        run(f"sed -i '/\\[Security\\]/a DenyUsers=root' {sesman_config}")
    
    if not file_contains(sesman_config, "MaxLoginRetry"):
        run(f"sed -i '/\\[Security\\]/a MaxLoginRetry=3' {sesman_config}")
    
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
        f.write("ls -lh /opt/infra_tools/steps/xrdp_session_cleanup.py 2>/dev/null || echo 'Cleanup script not found'\n\n")
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

