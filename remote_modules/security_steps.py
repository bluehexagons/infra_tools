"""Security hardening steps."""

import os
import shlex

from .utils import run, is_package_installed, is_service_active, file_contains


def create_remoteusers_group(**_) -> None:
    """Create remoteusers group for SSH and RDP access control."""
    result = run("getent group remoteusers", check=False)
    if result.returncode == 0:
        # Check if root is in the group
        result = run("id -nG root | grep -qw remoteusers", check=False)
        if result.returncode == 0:
            print("  ✓ remoteusers group already exists with root user")
            return
    else:
        run("groupadd remoteusers")
    
    # Add root to remoteusers group
    run("usermod -aG remoteusers root", check=False)
    print("  ✓ remoteusers group created and root user added")


def configure_firewall(os_type: str, **_) -> None:
    if os_type == "debian":
        result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
        if result.returncode == 0:
            print("  ✓ Firewall already configured")
            return
        
        run("apt-get install -y -qq ufw")
        run("ufw default deny incoming")
        run("ufw default allow outgoing")
        run("ufw allow ssh")
        run("ufw allow 3389/tcp")
        run("ufw --force enable")
    else:
        if is_service_active("firewalld"):
            result = run("firewall-cmd --query-port=3389/tcp", check=False)
            if result.returncode == 0:
                print("  ✓ Firewall already configured")
                return
        
        run("systemctl enable firewalld", check=False)
        run("systemctl start firewalld", check=False)
        run("firewall-cmd --permanent --add-service=ssh", check=False)
        run("firewall-cmd --permanent --add-port=3389/tcp", check=False)
        run("firewall-cmd --reload", check=False)

    print("  ✓ Firewall configured (SSH and RDP allowed)")


def configure_fail2ban(os_type: str, **_) -> None:
    if os.path.exists("/etc/fail2ban/jail.d/xrdp.local"):
        if is_service_active("fail2ban"):
            print("  ✓ fail2ban already configured")
            return

    if os_type == "debian":
        run("apt-get install -y -qq fail2ban")
    else:
        run("dnf install -y -q fail2ban")

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


def harden_ssh(**_) -> None:
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

    # Add AllowGroups directive if not present (root is in remoteusers group)
    if not file_contains(sshd_config, "AllowGroups"):
        run(f"echo 'AllowGroups remoteusers' >> /etc/ssh/sshd_config")

    run("systemctl reload sshd || systemctl reload ssh", check=False)

    print("  ✓ SSH hardened (key-only auth, timeouts, restricted to remoteusers group)")


def harden_kernel(**_) -> None:
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


def configure_auto_updates(os_type: str, **_) -> None:
    if os_type == "debian":
        if os.path.exists("/etc/apt/apt.conf.d/20auto-upgrades"):
            if is_service_active("unattended-upgrades"):
                print("  ✓ Automatic updates already configured")
                return
        
        run("apt-get install -y -qq unattended-upgrades")

        auto_upgrades = """APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
"""
        with open("/etc/apt/apt.conf.d/20auto-upgrades", "w") as f:
            f.write(auto_upgrades)

        run("systemctl enable unattended-upgrades")
        run("systemctl start unattended-upgrades")
    else:
        if is_service_active("dnf-automatic.timer"):
            print("  ✓ Automatic updates already configured")
            return
        
        run("dnf install -y -q dnf-automatic")
        run("sed -i 's/apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf")
        run("sed -i 's/upgrade_type = default/upgrade_type = security/' /etc/dnf/automatic.conf")
        run("systemctl enable dnf-automatic.timer")
        run("systemctl start dnf-automatic.timer")

    print("  ✓ Automatic security updates enabled")


def configure_firewall_web(os_type: str, **_) -> None:
    if os_type == "debian":
        result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
        if result.returncode == 0:
            # Check if HTTP/HTTPS already allowed
            result = run("ufw status | grep -q '80/tcp'", check=False)
            if result.returncode == 0:
                print("  ✓ Firewall already configured for web")
                return
        
        run("apt-get install -y -qq ufw")
        run("ufw default deny incoming")
        run("ufw default allow outgoing")
        run("ufw allow ssh")
        run("ufw allow 80/tcp")
        run("ufw allow 443/tcp")
        run("ufw --force enable")
    else:
        if is_service_active("firewalld"):
            result = run("firewall-cmd --query-service=http", check=False)
            if result.returncode == 0:
                print("  ✓ Firewall already configured for web")
                return
        
        run("systemctl enable firewalld", check=False)
        run("systemctl start firewalld", check=False)
        run("firewall-cmd --permanent --add-service=ssh", check=False)
        run("firewall-cmd --permanent --add-service=http", check=False)
        run("firewall-cmd --permanent --add-service=https", check=False)
        run("firewall-cmd --reload", check=False)
    
    print("  ✓ Firewall configured (SSH, HTTP, and HTTPS allowed)")


def configure_firewall_ssh_only(os_type: str, **_) -> None:
    """Configure firewall to allow only SSH (for servers without web/RDP)."""
    if os_type == "debian":
        result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
        if result.returncode == 0:
            print("  ✓ Firewall already configured")
            return
        
        run("apt-get install -y -qq ufw")
        run("ufw default deny incoming")
        run("ufw default allow outgoing")
        run("ufw allow ssh")
        run("ufw --force enable")
    else:
        if is_service_active("firewalld"):
            print("  ✓ Firewall already configured")
            return
        
        run("systemctl enable firewalld", check=False)
        run("systemctl start firewalld", check=False)
        run("firewall-cmd --permanent --add-service=ssh", check=False)
        run("firewall-cmd --reload", check=False)

    print("  ✓ Firewall configured (SSH only)")
