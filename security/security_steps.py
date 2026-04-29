"""Security hardening steps."""

from __future__ import annotations

import os

from lib.config import SetupConfig
from lib.maintenance_defaults import JOURNAL_MAX_USE
from lib.machine_state import can_modify_kernel, is_container
from lib.remote_utils import run
from lib.systemd_service import cleanup_service

_LEGACY_UNATTENDED_ORIGINS_FILE = "/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades"
_LEGACY_MANAGED_ORIGINS_FILE = "/etc/infra_tools/unattended_upgrades_origins.list"
_JOURNAL_CONF_DIR = "/etc/systemd/journald.conf.d"
_JOURNAL_CONF_FILE = f"{_JOURNAL_CONF_DIR}/infra-tools.conf"
_SSHD_DROPIN_DIR = "/etc/ssh/sshd_config.d"
_SSHD_DROPIN_FILE = f"{_SSHD_DROPIN_DIR}/99-infra-tools-hardening.conf"
_SYSCTL_HARDENING_FILE = "/etc/sysctl.d/99-security-hardening.conf"
_FAIL2BAN_SSHD_JAIL = "/etc/fail2ban/jail.d/sshd.local"
_FAIL2BAN_XRDP_JAIL = "/etc/fail2ban/jail.d/xrdp.local"
_FAIL2BAN_XRDP_FILTER = "/etc/fail2ban/filter.d/xrdp.conf"


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
        if config.enable_rdp:
            # Ensure RDP is rate-limited even if ufw was already active from a
            # prior run that used `ufw allow 3389/tcp`.
            run("ufw delete allow 3389/tcp", check=False)
            run("ufw limit 3389/tcp", check=False)
        return
    
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming", check=False)
    run("ufw default allow outgoing", check=False)
    run("ufw limit ssh", check=False)
    if config.enable_rdp:
        # `limit` rate-limits brute-force attempts at the firewall layer in
        # addition to fail2ban (defence in depth).
        run("ufw limit 3389/tcp", check=False)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return

    if config.enable_rdp:
        print("  ✓ Firewall configured (SSH and RDP rate-limited)")
    else:
        print("  ✓ Firewall configured (SSH rate-limited)")


def configure_fail2ban(config: SetupConfig) -> None:
    if is_container():
        print("  ✓ Skipping fail2ban configuration (limited functionality in containers)")
        return

    run("apt-get install -y -qq fail2ban")

    os.makedirs("/etc/fail2ban/filter.d", exist_ok=True)
    os.makedirs("/etc/fail2ban/jail.d", exist_ok=True)

    # SSH jail uses the upstream-shipped /etc/fail2ban/filter.d/sshd.conf which
    # is kept up to date by the Debian package.
    sshd_jail = """[sshd]
enabled = true
port = ssh
filter = sshd
backend = systemd
maxretry = 5
findtime = 600
bantime = 3600
"""

    with open(_FAIL2BAN_SSHD_JAIL, "w") as f:
        f.write(sshd_jail)

    if config.enable_rdp:
        # Filter modeled on upstream xrdp/instfiles/fail2ban/xrdp.conf and
        # adapted for xrdp 0.10 on Debian Trixie. AUTHFAIL is the canonical
        # failed-login marker emitted by xrdp-sesman.
        fail2ban_xrdp_filter = """# Fail2Ban filter for xrdp authentication failures
# Matches xrdp-sesman AUTHFAIL events emitted by xrdp >= 0.9.
[INCLUDES]
before = common.conf

[Definition]
_daemon = xrdp(-sesman)?

failregex = ^.*AUTHFAIL: user=\\S+ ip=<HOST>(?::\\d+)?\\s.*$
            ^.*\\[INFO \\]\\s+login failed for user \\S+ from <HOST>.*$
            ^.*\\[INFO \\]\\s+connection refused for user \\S+ from <HOST>.*$
ignoreregex =
"""

        fail2ban_xrdp_jail = """[xrdp]
enabled = true
port = 3389
protocol = tcp
filter = xrdp
logpath = /var/log/xrdp-sesman.log
           /var/log/xrdp.log
maxretry = 3
bantime = 3600
findtime = 600
"""

        with open(_FAIL2BAN_XRDP_FILTER, "w") as f:
            f.write(fail2ban_xrdp_filter)

        with open(_FAIL2BAN_XRDP_JAIL, "w") as f:
            f.write(fail2ban_xrdp_jail)

    run("systemctl enable fail2ban")
    run("systemctl restart fail2ban")

    if config.enable_rdp:
        print("  ✓ fail2ban configured (sshd + xrdp jails, 1 hour ban)")
    else:
        print("  ✓ fail2ban configured (sshd jail, 1 hour ban)")


def harden_ssh(config: SetupConfig) -> None:
    """Apply SSH hardening via a drop-in file under /etc/ssh/sshd_config.d/.

    Using a drop-in keeps the distro-shipped sshd_config untouched and makes
    the hardening idempotent across reruns and OpenSSH upgrades that move
    settings between files. The drop-in is read first by sshd, so its values
    win over later occurrences in the main config.
    """
    hardening_content = """# Managed by infra_tools - SSH hardening drop-in.
# Drop-ins under /etc/ssh/sshd_config.d/*.conf are read before the main
# sshd_config; the first-match-wins rule means these directives override
# anything later in /etc/ssh/sshd_config.
PermitRootLogin prohibit-password
PasswordAuthentication no
PermitEmptyPasswords no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
LoginGraceTime 30
AllowGroups remoteusers
"""

    os.makedirs(_SSHD_DROPIN_DIR, exist_ok=True)

    if os.path.exists(_SSHD_DROPIN_FILE):
        try:
            with open(_SSHD_DROPIN_FILE, "r") as f:
                existing = f.read()
        except OSError:
            existing = None
        if existing == hardening_content:
            print("  ✓ SSH already hardened")
            return

    with open(_SSHD_DROPIN_FILE, "w") as f:
        f.write(hardening_content)

    # Validate the resulting config before reloading so we do not lock out
    # access if a future change introduces a typo.
    validate = run("sshd -t", check=False)
    if validate.returncode != 0:
        print("  ⚠ sshd -t failed after hardening drop-in; leaving previous config active")
        return

    run("systemctl reload sshd || systemctl reload ssh", check=False)

    print("  ✓ SSH hardened (drop-in: key-only auth, timeouts, AllowGroups remoteusers)")


def harden_kernel(config: SetupConfig) -> None:
    if not can_modify_kernel():
        print("  ✓ Skipping kernel hardening (host kernel manages these settings)")
        return

    kernel_hardening = """# Managed by infra_tools - kernel security hardening.
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
kernel.unprivileged_bpf_disabled=1
net.core.bpf_jit_harden=2
fs.suid_dumpable=0
fs.protected_hardlinks=1
fs.protected_symlinks=1
fs.protected_fifos=2
fs.protected_regular=2
"""

    if os.path.exists(_SYSCTL_HARDENING_FILE):
        try:
            with open(_SYSCTL_HARDENING_FILE, "r") as f:
                existing = f.read()
        except OSError:
            existing = None
        if existing == kernel_hardening:
            print("  ✓ Kernel already hardened")
            return

    with open(_SYSCTL_HARDENING_FILE, "w") as f:
        f.write(kernel_hardening)

    result = run(f"sysctl -p {_SYSCTL_HARDENING_FILE}", check=False)
    if result.returncode != 0:
        print("  ⚠ Some kernel parameters may not have applied (check logs)")

    print("  ✓ Kernel hardened (network protection, security restrictions)")


def _cleanup_legacy_unattended_upgrades() -> None:
    """Remove legacy unattended-upgrades config files created by older versions."""
    for path in (_LEGACY_UNATTENDED_ORIGINS_FILE, _LEGACY_MANAGED_ORIGINS_FILE):
        if os.path.exists(path):
            os.remove(path)


def configure_auto_updates(config: SetupConfig) -> None:
    """Configure automatic package updates using a custom systemd service.

    This replaces the legacy unattended-upgrades approach. The new service
    runs ``apt-get update && apt-get dist-upgrade`` which:
    - Does not require any hardcoded origins or codenames
    - Automatically handles all configured repositories
    - Supports release version switches (dist-upgrade resolves dependency changes)
    """
    service_name = "auto-update-apt"
    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"

    # Clean up any existing service/timer before creating new ones
    cleanup_service(service_name)

    # Remove legacy unattended-upgrades config files from older setups
    _cleanup_legacy_unattended_upgrades()

    # Stop and disable unattended-upgrades to prevent dpkg lock conflicts
    # with our custom auto-update service.
    run("systemctl stop unattended-upgrades", check=False)
    run("systemctl disable unattended-upgrades", check=False)

    script_path = "/opt/infra_tools/common/service_tools/auto_update_apt.py"

    service_content = f"""[Unit]
Description=Auto-update APT packages
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script_path}
StandardOutput=journal
StandardError=journal
"""

    with open(service_file, "w") as f:
        f.write(service_content)

    timer_content = """[Unit]
Description=Auto-update APT packages (daily at 6 AM)
Documentation=man:systemd.timer(5)

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
"""

    with open(timer_file, "w") as f:
        f.write(timer_content)

    result = run("systemctl daemon-reload", check=False)
    if result.returncode != 0:
        print("  ⚠ Automatic updates configured but systemd could not reload")
        return
    run("systemctl enable auto-update-apt.timer", check=False)
    run("systemctl start auto-update-apt.timer", check=False)

    print("  ✓ Automatic package updates enabled (daily at 6 AM)")


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
    run("ufw limit ssh", check=False)
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
    run("ufw limit ssh", check=False)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return

    print("  ✓ Firewall configured (SSH rate-limited)")


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


def configure_cleanup_maintenance(config: SetupConfig) -> None:
    """Configure periodic cleanup for journals, temp files, and package caches."""
    service_name = "cleanup-maintenance"
    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    script_path = "/opt/infra_tools/common/service_tools/cleanup_maintenance.py"

    cleanup_service(service_name)

    os.makedirs(_JOURNAL_CONF_DIR, exist_ok=True)
    with open(_JOURNAL_CONF_FILE, "w") as f:
        f.write(
            f"""[Journal]
SystemMaxUse={JOURNAL_MAX_USE}
RuntimeMaxUse={JOURNAL_MAX_USE}
"""
        )

    service_content = f"""[Unit]
Description=Cleanup temporary files and package caches
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script_path}
StandardOutput=journal
StandardError=journal
"""

    with open(service_file, "w") as f:
        f.write(service_content)

    timer_content = """[Unit]
Description=Cleanup temporary files and package caches (weekly)
Documentation=man:systemd.timer(5)

[Timer]
OnCalendar=Sun *-*-* 03:30:00
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
"""

    with open(timer_file, "w") as f:
        f.write(timer_content)

    result = run("systemctl daemon-reload", check=False)
    if result.returncode != 0:
        print("  ⚠ Cleanup maintenance configured but systemd could not reload")
        return

    journal_result = run("systemctl restart systemd-journald", check=False)
    if journal_result.returncode != 0:
        print("  ⚠ Cleanup maintenance configured but journald could not be restarted")

    enable_result = run("systemctl enable cleanup-maintenance.timer", check=False)
    if enable_result.returncode != 0:
        print("  ⚠ Cleanup maintenance configured but timer could not be enabled")
        return

    start_result = run("systemctl start cleanup-maintenance.timer", check=False)
    if start_result.returncode != 0:
        print("  ⚠ Cleanup maintenance configured but timer could not be started")
        return

    print(f"  ✓ Cleanup maintenance enabled (weekly with {JOURNAL_MAX_USE} journal cap)")
