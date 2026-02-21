"""Security hardening steps."""

from __future__ import annotations

import os

from lib.config import SetupConfig
from lib.machine_state import can_modify_kernel, is_container
from lib.remote_utils import run, is_service_active, file_contains
from lib.systemd_service import cleanup_service

UNATTENDED_ORIGINS_FILE = "/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades"


def create_remoteusers_group(config: SetupConfig) -> None:
    """Create remoteusers group for SSH and RDP access control."""
    result = run("getent group remoteusers", check=False)
    group_exists = result.returncode == 0
    
    if not group_exists:
        run("groupadd remoteusers")
    
    result = run("id -nG root | grep -qw remoteusers", check=False)
    if result.returncode != 0:
        run("usermod -aG remoteusers root")
        print("  ✓ remoteusers group created and root user added")
    else:
        print("  ✓ remoteusers group already exists with root user")


def configure_firewall(config: SetupConfig) -> None:
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        print("  ✓ Firewall already configured")
        return
    
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming", check=False)
    run("ufw default allow outgoing", check=False)
    run("ufw allow ssh", check=False)
    if config.enable_rdp:
        run("ufw allow 3389/tcp", check=False)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return

    if config.enable_rdp:
        print("  ✓ Firewall configured (SSH and RDP allowed)")
    else:
        print("  ✓ Firewall configured (SSH allowed)")


def configure_fail2ban(config: SetupConfig) -> None:
    if is_container():
        print("  ✓ Skipping fail2ban configuration (limited functionality in containers)")
        return
    
    if os.path.exists("/etc/fail2ban/jail.d/xrdp.local"):
        if is_service_active("fail2ban"):
            print("  ✓ fail2ban already configured")
            return

    run("apt-get install -y -qq fail2ban")

    fail2ban_xrdp_filter = """[Definition]
failregex = ^.*xrdp-sesman.*: .*login failed for user.*from ip <HOST>.*$
            ^.*xrdp.*: .*connection from <HOST>.*failed.*$
ignoreregex =
"""

    fail2ban_xrdp_jail = """[xrdp]
enabled = true
port = 3389
protocol = tcp
filter = xrdp
logpath = /var/log/xrdp-sesman.log
maxretry = 3
bantime = 3600
findtime = 600
"""

    os.makedirs("/etc/fail2ban/filter.d", exist_ok=True)
    os.makedirs("/etc/fail2ban/jail.d", exist_ok=True)

    with open("/etc/fail2ban/filter.d/xrdp.conf", "w") as f:
        f.write(fail2ban_xrdp_filter)

    with open("/etc/fail2ban/jail.d/xrdp.local", "w") as f:
        f.write(fail2ban_xrdp_jail)

    run("systemctl enable fail2ban")
    run("systemctl restart fail2ban")

    print("  ✓ fail2ban configured (3 failed attempts = 1 hour ban)")


def harden_ssh(config: SetupConfig) -> None:
    sshd_config = "/etc/ssh/sshd_config"
    
    if file_contains(sshd_config, "PasswordAuthentication no"):
        if file_contains(sshd_config, "MaxAuthTries 3"):
            if file_contains(sshd_config, "AllowGroups"):
                print("  ✓ SSH already hardened")
                return

    if not os.path.exists("/etc/ssh/sshd_config.bak"):
        run("cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak")

    ssh_hardening = [
        ("PermitRootLogin", "prohibit-password"),
        ("PasswordAuthentication", "no"),
        ("X11Forwarding", "no"),
        ("MaxAuthTries", "3"),
        ("ClientAliveInterval", "300"),
        ("ClientAliveCountMax", "2"),
        ("PermitEmptyPasswords", "no"),
    ]

    for key, value in ssh_hardening:
        run(f"sed -i 's/^#*{key}.*/{key} {value}/' /etc/ssh/sshd_config")

    if not file_contains(sshd_config, "AllowGroups"):
        run(f"echo 'AllowGroups remoteusers' >> /etc/ssh/sshd_config")

    run("systemctl reload sshd || systemctl reload ssh", check=False)

    print("  ✓ SSH hardened (key-only auth, timeouts, restricted to remoteusers group)")


def harden_kernel(config: SetupConfig) -> None:
    if not can_modify_kernel():
        print("  ✓ Skipping kernel hardening (host kernel manages these settings)")
        return
    
    sysctl_conf = "/etc/sysctl.d/99-security-hardening.conf"
    
    if os.path.exists(sysctl_conf):
        print("  ✓ Kernel already hardened")
        return
    
    kernel_hardening = """
# Network security
net.ipv4.conf.default.rp_filter=1
net.ipv4.conf.all.rp_filter=1
net.ipv4.tcp_syncookies=1
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv4.conf.all.secure_redirects=0
net.ipv4.conf.default.secure_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ignore_bogus_error_responses=1
net.ipv4.conf.all.log_martians=1
net.ipv4.conf.default.log_martians=1

# Kernel security
kernel.dmesg_restrict=1
kernel.kptr_restrict=2
kernel.yama.ptrace_scope=1
fs.suid_dumpable=0
"""
    
    with open(sysctl_conf, "w") as f:
        f.write(kernel_hardening)
    
    result = run("sysctl -p /etc/sysctl.d/99-security-hardening.conf", check=False)
    if result.returncode != 0:
        print("  ⚠ Some kernel parameters may not have applied (check logs)")
    
    print("  ✓ Kernel hardened (network protection, security restrictions)")


def configure_auto_updates(config: SetupConfig) -> None:
    if os.path.exists("/etc/apt/apt.conf.d/20auto-upgrades"):
        if os.path.exists(UNATTENDED_ORIGINS_FILE) and is_service_active("unattended-upgrades"):
            print("  ✓ Automatic updates already configured")
            return
    
    run("apt-get install -y -qq unattended-upgrades")

    # The default unattended-upgrades timer runs daily around 6:00 AM + random delay
    # This is before our 2:00 AM restart window (next day), giving time for updates to settle
    auto_upgrades = """APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
"""
    with open("/etc/apt/apt.conf.d/20auto-upgrades", "w") as f:
        f.write(auto_upgrades)

    origins = [
        "origin=${distro_id},codename=${distro_codename}",
        "origin=${distro_id},codename=${distro_codename}-security",
        "origin=${distro_id},codename=${distro_codename}-updates",
    ]
    if os.path.exists("/etc/apt/sources.list.d/vscode.list"):
        origins.append("origin=packages.microsoft.com")
    if os.path.exists("/etc/apt/sources.list.d/brave-browser-release.list"):
        origins.append("origin=Brave Software")

    update_origins = "Unattended-Upgrade::Origins-Pattern {\n"
    for origin in origins:
        update_origins += f'        "{origin}";\n'
    update_origins += "};\n"

    with open(UNATTENDED_ORIGINS_FILE, "w") as f:
        f.write(update_origins)

    # systemctl may not be available or functional in containers
    result = run("systemctl enable unattended-upgrades", check=False)
    if result.returncode != 0:
        print("  ⚠ Automatic updates configured but systemd service could not be enabled")
        return
    run("systemctl start unattended-upgrades", check=False)

    print("  ✓ Automatic package updates enabled")


def ensure_unattended_upgrade_origin(origin: str) -> None:
    """Ensure a specific origin is included in unattended-upgrades origins file."""
    if not os.path.exists(UNATTENDED_ORIGINS_FILE):
        return

    entry = f'"origin={origin}";'
    with open(UNATTENDED_ORIGINS_FILE, "r") as f:
        content = f.read()
    if entry in content:
        return

    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == "};":
            lines.insert(i, f"        {entry}\n")
            break
    else:
        print("  ⚠ unattended-upgrades origins file format unexpected; could not add origin")
        return

    with open(UNATTENDED_ORIGINS_FILE, "w") as f:
        f.write("".join(lines))


def configure_firewall_web(config: SetupConfig) -> None:
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        result = run("ufw status | grep -q '80/tcp'", check=False)
        if result.returncode == 0:
            print("  ✓ Firewall already configured for web")
            return
    
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming", check=False)
    run("ufw default allow outgoing", check=False)
    run("ufw allow ssh", check=False)
    run("ufw allow 80/tcp", check=False)
    run("ufw allow 443/tcp", check=False)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return
    
    print("  ✓ Firewall configured (SSH, HTTP, and HTTPS allowed)")


def configure_firewall_ssh_only(config: SetupConfig) -> None:
    """Configure firewall to allow only SSH (for servers without web/RDP)."""
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        print("  ✓ Firewall already configured")
        return
    
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming", check=False)
    run("ufw default allow outgoing", check=False)
    run("ufw allow ssh", check=False)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return

    print("  ✓ Firewall configured (SSH only)")


def configure_auto_restart(config: SetupConfig) -> None:
    """Configure automatic restart at 2 AM when updates require it."""
    service_name = "auto-restart-if-needed"
    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    
    # Clean up any existing service/timer before creating new ones
    cleanup_service(service_name)
    
    script_path = "/opt/infra_tools/common/service_tools/auto_restart_if_needed.py"
    
    service_content = f"""[Unit]
Description=Auto-restart system if needed
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script_path}
"""
    
    with open(service_file, "w") as f:
        f.write(service_content)
    
    timer_content = """[Unit]
Description=Auto-restart system if needed (daily at 2 AM)
Documentation=man:systemd.timer(5)

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
"""
    
    with open(timer_file, "w") as f:
        f.write(timer_content)
    
    run("systemctl daemon-reload")
    run("systemctl enable auto-restart-if-needed.timer")
    run("systemctl start auto-restart-if-needed.timer")
    
    print("  ✓ Automatic restart service configured (daily at 2 AM when needed)")
