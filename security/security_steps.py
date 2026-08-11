"""Security hardening steps."""

from __future__ import annotations

import os
import re
import shlex
import shutil

from lib.maintenance_systemd import configure_maintenance_timer
from lib.config import SetupConfig
from lib.maintenance_defaults import JOURNAL_MAX_USE
from lib.machine_state import can_modify_kernel, is_container, is_hardware, is_vm
from lib.remote_utils import is_dry_run, run
from lib.validation import validate_network_ip_or_cidr

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
_AUDIT_RULES_FILE = "/etc/audit/rules.d/99-infra-tools.rules"
_FAILLOCK_CONF = "/etc/security/faillock.conf"
_PAM_FAILLOCK_PROFILE = "/usr/share/pam-configs/faillock-infra-tools"
_ISSUE_BANNER = "Authorized access only. All activity is monitored and logged.\n"
_SECURITY_MONITOR_SCRIPT = "/opt/infra_tools/security/service_tools/security_monitor.py"
_RDP_RULE_COMMENT_PREFIX = "infra_tools RDP"
_UFW_NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]")


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


def _rdp_firewall_rules(config: SetupConfig) -> list[tuple[str, str]]:
    """Return validated UFW comment/command pairs for the requested RDP policy."""
    sources = [
        validate_network_ip_or_cidr(source, "RDP source")
        for source in config.rdp_allowed_sources or []
    ]
    if not sources:
        comment = f"{_RDP_RULE_COMMENT_PREFIX} global"
        return [(comment, f"ufw limit 3389/tcp comment {shlex.quote(comment)}")]

    rules: list[tuple[str, str]] = []
    for source in sources:
        comment = f"{_RDP_RULE_COMMENT_PREFIX} source {source}"
        rules.append(
            (
                comment,
                "ufw limit from "
                f"{shlex.quote(source)} to any port 3389 proto tcp "
                f"comment {shlex.quote(comment)}",
            )
        )
    return rules


def _remove_stale_managed_rdp_rules(desired_comments: set[str]) -> None:
    """Remove obsolete comment-tagged RDP rules in descending UFW order."""
    result = run("ufw status numbered", check=False, capture_output=True)
    stdout = getattr(result, "stdout", None)
    if result.returncode != 0 or not isinstance(stdout, str):
        return

    stale_rule_numbers: list[int] = []
    for line in stdout.splitlines():
        if "#" not in line:
            continue
        comment = line.split("#", 1)[1].strip()
        if not comment.startswith(_RDP_RULE_COMMENT_PREFIX):
            continue
        if comment in desired_comments:
            continue
        match = _UFW_NUMBERED_RULE_RE.match(line.strip())
        if match:
            stale_rule_numbers.append(int(match.group(1)))

    for rule_number in sorted(stale_rule_numbers, reverse=True):
        run(f"ufw --force delete {rule_number}", check=False)


def _configure_rdp_firewall(config: SetupConfig) -> None:
    """Apply RDP rules without removing broad access before replacements exist."""
    rules = _rdp_firewall_rules(config)
    has_restricted_sources = bool(config.rdp_allowed_sources)

    if not has_restricted_sources:
        # A legacy untagged limit rule is indistinguishable from the desired
        # global rule to UFW. Replace it so future reruns can reconcile by tag.
        run("ufw delete allow 3389/tcp", check=False)
        run("ufw delete limit 3389/tcp", check=False)

    for _comment, command in rules:
        result = run(command, check=False)
        if result.returncode != 0:
            if not has_restricted_sources:
                # Preserve the pre-existing reachability contract if tagging
                # the replacement global rule unexpectedly fails.
                run("ufw limit 3389/tcp", check=False)
            raise RuntimeError("Failed to install the requested RDP firewall rule")

    if has_restricted_sources:
        # Replacements are active before broad legacy access is removed.
        run("ufw delete allow 3389/tcp", check=False)
        run("ufw delete limit 3389/tcp", check=False)

    _remove_stale_managed_rdp_rules({comment for comment, _command in rules})


def configure_firewall(config: SetupConfig) -> None:
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        print("  ✓ Firewall already configured")
        if config.enable_rdp:
            _configure_rdp_firewall(config)
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming", check=False)
    run("ufw default allow outgoing", check=False)
    run("ufw limit ssh", check=False)
    if config.enable_rdp:
        _configure_rdp_firewall(config)
    
    result = run("ufw --force enable", check=False)
    if result.returncode != 0:
        if is_container():
            print("  ⚠ Firewall could not be enabled (container may lack capabilities)")
        else:
            print("  ⚠ Firewall could not be enabled (check logs)")
        return

    if config.enable_rdp:
        if config.rdp_allowed_sources:
            print("  ✓ Firewall configured (SSH rate-limited; RDP source-restricted)")
        else:
            print("  ✓ Firewall configured (SSH and global RDP rate-limited)")
    else:
        print("  ✓ Firewall configured (SSH rate-limited)")


def configure_fail2ban(config: SetupConfig) -> None:
    if is_dry_run():
        print("  [DRY-RUN] Would configure fail2ban jails")
        return

    if is_container():
        print("  ✓ Skipping fail2ban configuration (limited functionality in containers)")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
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

    if is_dry_run():
        print("  [DRY-RUN] Would apply the managed SSH hardening drop-in")
        return

    sshd_path = shutil.which("sshd")
    if sshd_path is None:
        for candidate in ("/usr/sbin/sshd", "/usr/lib/openssh/sshd"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                sshd_path = candidate
                break
    if sshd_path is None:
        print("  ✓ Skipping SSH hardening (openssh-server is not installed)")
        return

    try:
        os.makedirs(_SSHD_DROPIN_DIR, exist_ok=True)
    except OSError as exc:
        print(
            "  ⚠ Skipping SSH hardening (cannot access "
            f"{_SSHD_DROPIN_DIR}: {exc})"
        )
        return

    existing: str | None = None
    if os.path.exists(_SSHD_DROPIN_FILE):
        try:
            with open(_SSHD_DROPIN_FILE, "r") as f:
                existing = f.read()
        except OSError as exc:
            print(f"  ⚠ Could not read existing SSH hardening drop-in; leaving it unchanged: {exc}")
            return
        if existing == hardening_content:
            print("  ✓ SSH already hardened")
            return

    try:
        with open(_SSHD_DROPIN_FILE, "w") as f:
            f.write(hardening_content)
    except OSError as exc:
        print(
            "  ⚠ Skipping SSH hardening (cannot write "
            f"{_SSHD_DROPIN_FILE}: {exc})"
        )
        return

    # Validate the resulting config before reloading so we do not lock out
    # access if a future change introduces a typo.
    validate = run(f"{shlex.quote(sshd_path)} -t", check=False)
    if validate.returncode != 0:
        try:
            if existing is None:
                os.remove(_SSHD_DROPIN_FILE)
            else:
                with open(_SSHD_DROPIN_FILE, "w") as f:
                    f.write(existing)
        except OSError as exc:
            print(f"  ⚠ Failed to restore the previous SSH hardening drop-in: {exc}")
            return
        print("  ⚠ sshd -t failed after hardening drop-in; restored previous configuration")
        return

    run("systemctl reload sshd || systemctl reload ssh", check=False)

    print("  ✓ SSH hardened (drop-in: key-only auth, timeouts, AllowGroups remoteusers)")


def harden_kernel(config: SetupConfig) -> None:
    if is_dry_run():
        print("  [DRY-RUN] Would apply kernel hardening parameters")
        return

    if not can_modify_kernel():
        print("  ✓ Skipping kernel hardening (host kernel manages these settings)")
        return

    rp_filter_hardening = """net.ipv4.conf.default.rp_filter=1
net.ipv4.conf.all.rp_filter=1
"""
    if config.system_type == "server_proxmox":
        # A Proxmox host may route, NAT, or bridge traffic for guests. Strict
        # reverse-path filtering drops valid asymmetric guest traffic, so keep
        # the kernel's permissive default for this control-plane role.
        rp_filter_hardening = """# Proxmox hosts may route, NAT, or bridge guest traffic.
# Keep reverse-path filtering disabled to allow asymmetric guest paths.
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.all.rp_filter=0
"""

    kernel_hardening = f"""# Managed by infra_tools - kernel security hardening.
# Network security
{rp_filter_hardening}net.ipv4.tcp_syncookies=1
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
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv6.conf.all.accept_source_route=0
net.ipv6.conf.default.accept_source_route=0

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
kernel.core_uses_pid=1
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


def configure_login_banners(config: SetupConfig) -> None:
    if is_dry_run():
        print("  [DRY-RUN] Would configure login banners")
        return

    changed = False
    for path in ("/etc/issue", "/etc/issue.net"):
        try:
            with open(path) as f:
                existing = f.read()
        except OSError:
            existing = None
        if existing != _ISSUE_BANNER:
            with open(path, "w") as f:
                f.write(_ISSUE_BANNER)
            changed = True

    if changed:
        print("  ✓ Login banners configured (authorized-use notice)")
    else:
        print("  ✓ Login banners already configured")


def configure_apparmor(config: SetupConfig) -> None:
    if not (is_vm() or is_hardware()):
        print("  ✓ Skipping AppArmor setup (privileged containers inherit host AppArmor)")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq apparmor apparmor-utils")

    result = run("aa-status --json 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d.get('profiles') else 1)\"", check=False)
    if result.returncode == 0:
        # AppArmor is running; enforce all loaded profiles
        run("aa-enforce /etc/apparmor.d/* 2>/dev/null || true", check=False)
        run("systemctl enable apparmor", check=False)
        print("  ✓ AppArmor enabled (enforce mode for all installed profiles)")
    else:
        run("systemctl enable apparmor", check=False)
        run("systemctl restart apparmor", check=False)
        run("aa-enforce /etc/apparmor.d/* 2>/dev/null || true", check=False)
        print("  ✓ AppArmor configured (enforce mode; reboot may be needed to fully activate)")


def configure_auditd(config: SetupConfig) -> None:
    if is_dry_run():
        print("  [DRY-RUN] Would configure auditd rules")
        return

    if not (is_vm() or is_hardware()):
        print("  ✓ Skipping auditd (not applicable to containers)")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq auditd audispd-plugins")

    audit_rules = """# Managed by infra_tools - audit rules.
# Identity and authentication files
-w /etc/passwd -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers

# SSH configuration changes
-w /etc/ssh/sshd_config -p wa -k sshd_config
-w /etc/ssh/sshd_config.d/ -p wa -k sshd_config

# Privileged command execution (setuid/setgid by non-root sessions)
-a always,exit -F arch=b64 -S execve -F euid=0 -F auid>=1000 -F auid!=-1 -k privileged
-a always,exit -F arch=b32 -S execve -F euid=0 -F auid>=1000 -F auid!=-1 -k privileged

# Kernel module loading/unloading
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules
-a always,exit -F arch=b64 -S init_module,finit_module,delete_module -k modules

# Login and session tracking
-w /var/run/utmp -p wa -k session
-w /var/log/wtmp -p wa -k session
-w /var/log/btmp -p wa -k session

# Enable audit (not immutable - allows future rule updates)
-e 1
"""

    os.makedirs("/etc/audit/rules.d", exist_ok=True)

    if os.path.exists(_AUDIT_RULES_FILE):
        try:
            with open(_AUDIT_RULES_FILE) as f:
                existing = f.read()
        except OSError:
            existing = None
        if existing == audit_rules:
            print("  ✓ auditd already configured")
            return

    with open(_AUDIT_RULES_FILE, "w") as f:
        f.write(audit_rules)

    run("systemctl enable auditd")
    run("systemctl restart auditd", check=False)
    run("augenrules --load", check=False)

    print("  ✓ auditd configured (monitoring identity, sudoers, SSH config, modules)")


def configure_pam_lockout(config: SetupConfig) -> None:
    if is_dry_run():
        print("  [DRY-RUN] Would configure PAM account lockout")
        return

    if not (is_vm() or is_hardware()):
        print("  ✓ Skipping PAM lockout (not applicable to containers)")
        return

    faillock_conf = """# Managed by infra_tools - account lockout settings.
deny = 5
fail_interval = 900
unlock_time = 600
"""

    pam_profile = """Name: infra-tools account lockout (pam_faillock)
Default: yes
Priority: 0
Auth-Type: Primary
Auth:
\t[default=die] pam_faillock.so authfail
Auth-Initial:
\trequired pam_faillock.so preauth
Account-Type: Primary
Account:
\trequired pam_faillock.so
"""

    if os.path.exists(_FAILLOCK_CONF) and os.path.exists(_PAM_FAILLOCK_PROFILE):
        try:
            with open(_FAILLOCK_CONF) as f:
                if f.read() == faillock_conf:
                    print("  ✓ PAM lockout already configured")
                    return
        except OSError:
            pass

    os.makedirs("/usr/share/pam-configs", exist_ok=True)
    with open(_PAM_FAILLOCK_PROFILE, "w") as f:
        f.write(pam_profile)

    with open(_FAILLOCK_CONF, "w") as f:
        f.write(faillock_conf)

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    result = run("pam-auth-update --enable faillock-infra-tools", check=False)
    if result.returncode != 0:
        print("  ⚠ PAM auth update failed; lockout config written but may not be active")
        return

    print("  ✓ PAM account lockout configured (5 failures in 15 min → 10 min lockout)")


def configure_security_monitor(config: SetupConfig) -> None:
    """Set up a systemd timer that checks security logs every 15 minutes.

    Monitors fail2ban ban events, auditd key events (identity, sudoers, SSH
    config, kernel modules, privileged execs), and SSH auth failures, then
    sends notifications via the configured infra_tools targets.
    """
    if not (is_vm() or is_hardware()):
        print("  ✓ Skipping security monitor (not applicable to containers)")
        return

    configured = configure_maintenance_timer(
        service_name="security-monitor",
        service_desc="Security event monitor",
        timer_desc="Security event monitor (every 15 minutes)",
        script_path=_SECURITY_MONITOR_SCRIPT,
        schedule="*:0/15",
        check_name="Security event monitor",
        randomized_delay="2min",
        timeout="10min",
        purpose="monitor",
    )
    if not configured:
        raise RuntimeError("Security event monitor timer failed verification")


def _cleanup_legacy_unattended_upgrades() -> None:
    """Remove legacy unattended-upgrades config files created by older versions."""
    for path in (_LEGACY_UNATTENDED_ORIGINS_FILE, _LEGACY_MANAGED_ORIGINS_FILE):
        if os.path.exists(path):
            os.remove(path)


def configure_auto_updates(config: SetupConfig) -> None:
    """Configure automatic package updates using a custom systemd service.

    This replaces the legacy unattended-upgrades approach. The new service
    runs ``apt-get update && apt-get dist-upgrade --no-remove`` which:
    - Does not require any hardcoded origins or codenames
    - Automatically handles all configured repositories
    - Supports dependency additions while refusing automated package removals
    """
    if is_dry_run():
        print("  [DRY-RUN] Would configure automatic package updates")
        return

    # Remove legacy unattended-upgrades config files from older setups
    _cleanup_legacy_unattended_upgrades()

    configured = configure_maintenance_timer(
        service_name="auto-update-apt",
        service_desc="Auto-update APT packages",
        timer_desc="Auto-update APT packages daily",
        script_path="/opt/infra_tools/common/service_tools/auto_update_apt.py",
        schedule="*-*-* 06:00:00",
        check_name="APT packages",
        purpose="auto-update",
    )
    if not configured:
        print("  ⚠ Replacement APT update timer was not verified; retaining distro APT timers")
        raise RuntimeError("APT update timer failed verification")

    # The distro timers can invoke unattended-upgrades even when its service is
    # disabled. Retire those competing activators only after the replacement is
    # active so a failed setup cannot leave the host without automatic updates.
    for unit in (
        "unattended-upgrades.service",
        "apt-daily.timer",
        "apt-daily-upgrade.timer",
    ):
        run(f"systemctl stop {unit}", check=False)
        run(f"systemctl disable {unit}", check=False)


def configure_firewall_web(config: SetupConfig) -> None:
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        result = run("ufw status | grep -q '80/tcp'", check=False)
        if result.returncode == 0:
            print("  ✓ Firewall already configured for web")
            return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
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

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
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
    if not can_modify_kernel():
        print("  ✓ Skipping automatic restart service (container)")
        return

    configured = configure_maintenance_timer(
        service_name="auto-restart-if-needed",
        service_desc="Auto-restart system if needed",
        timer_desc="Auto-restart system if needed (daily at 2 AM)",
        script_path="/opt/infra_tools/common/service_tools/auto_restart_if_needed.py",
        schedule="*-*-* 02:00:00",
        on_boot_sec="30min",
        check_name="Automatic restart",
        randomized_delay="10min",
        timeout="10min",
        network_online=False,
        purpose="check",
    )
    if not configured:
        raise RuntimeError("Automatic restart timer failed verification")


def configure_cleanup_maintenance(config: SetupConfig) -> None:
    """Configure periodic cleanup for journals, temp files, and package caches."""
    if is_dry_run():
        print("  [DRY-RUN] Would configure cleanup maintenance")
        return

    os.makedirs(_JOURNAL_CONF_DIR, exist_ok=True)
    with open(_JOURNAL_CONF_FILE, "w") as f:
        f.write(
            f"""[Journal]
SystemMaxUse={JOURNAL_MAX_USE}
RuntimeMaxUse={JOURNAL_MAX_USE}
"""
        )

    journal_result = run("systemctl restart systemd-journald", check=False)
    if journal_result.returncode != 0:
        print("  ⚠ Journal limits written but journald could not be restarted")

    configured = configure_maintenance_timer(
        service_name="cleanup-maintenance",
        service_desc="Cleanup temporary files and package caches",
        timer_desc="Cleanup temporary files and package caches (weekly)",
        script_path="/opt/infra_tools/common/service_tools/cleanup_maintenance.py",
        schedule="Sun *-*-* 03:30:00",
        check_name="Cleanup maintenance",
        randomized_delay="30min",
        timeout="1h",
        network_online=False,
        purpose="job",
    )
    if not configured:
        raise RuntimeError("Cleanup maintenance timer failed verification")
