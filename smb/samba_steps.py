from __future__ import annotations

import os
import shlex
import re
from typing import Optional, Any

from lib.config import SetupConfig
from lib.mount_utils import is_path_under_mnt, get_mount_ancestor
from lib.remote_utils import run, is_package_installed


def parse_share_credentials(
    credential_specs: Optional[list[list[str]]]
) -> dict[str, str]:
    credentials: dict[str, str] = {}
    if not credential_specs:
        return credentials

    for credential_spec in credential_specs:
        if not credential_spec or len(credential_spec) < 2:
            raise ValueError(
                f"Credential spec requires: username password (got: {credential_spec})"
            )

        username = credential_spec[0].strip()
        password = credential_spec[1].strip()
        if not username:
            raise ValueError("Credential username must not be empty")

        credentials[username] = password

    return credentials


def install_samba(config: SetupConfig) -> None:
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq samba samba-common-bin")
    
    run("systemctl enable smbd")
    run("systemctl start smbd")
    
    print("  ✓ Samba installed/updated and service started")


def configure_samba_firewall(config: SetupConfig) -> None:
    # Modern SMB only needs 445/tcp. NetBIOS (137/138/139) is disabled in the
    # global Samba config (`disable netbios = yes`), so opening 139/tcp would
    # only widen the attack surface for no benefit. Remove any pre-existing
    # 139/tcp rule that an earlier version of this tool may have added.
    cleanup_rules = [
        "ufw delete allow 139/tcp",
        "ufw delete allow 139",
    ]
    for rule in cleanup_rules:
        run(rule, check=False)

    result = run("ufw allow 445/tcp comment 'Samba SMB'", check=False)
    if result.returncode != 0:
        print("  Warning: Failed to add firewall rule for SMB (445/tcp)")

    run("ufw reload", check=False)
    print("  ✓ Firewall configured for Samba (445/tcp)")


def parse_share_spec(
    share_spec: Optional[list[str]],
    credentials: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    if not share_spec or len(share_spec) < 4:
        raise ValueError("Share spec requires: access_type share_name paths users")
    
    access_type = share_spec[0]
    if access_type not in ["read", "write"]:
        raise ValueError(f"Invalid access type: {access_type}. Must be 'read' or 'write'")
    
    share_name = share_spec[1]
    paths_str = share_spec[2]
    users_str = share_spec[3]
    
    paths = [p.strip() for p in paths_str.split(',') if p.strip()]
    
    users: list[dict[str, str]] = []
    for user_spec in users_str.split(','):
        user_spec = user_spec.strip()
        if not user_spec:
            continue
        if ':' in user_spec:
            username, password = user_spec.split(':', 1)
        elif credentials and user_spec in credentials:
            username = user_spec
            password = credentials[user_spec]
        else:
            raise ValueError(
                f"Missing credential for share user: {user_spec}. "
                "Use 'username:password' or provide --credential USERNAME PASSWORD"
            )
        users.append({'username': username.strip(), 'password': password.strip()})
    
    return {
        'access_type': access_type,
        'share_name': share_name,
        'paths': paths,
        'users': users
    }


def validate_samba_share_credentials(config: SetupConfig) -> None:
    if not config.samba_shares:
        return

    credentials = parse_share_credentials(config.share_credentials)
    for share_spec in config.samba_shares:
        parse_share_spec(share_spec, credentials)


def create_samba_user(username: str, password: str) -> None:
    safe_username = shlex.quote(username)
    
    result = run(f"id {safe_username}", check=False)
    if result.returncode != 0:
        run(f"useradd -M -s /usr/sbin/nologin {safe_username}")
        print(f"  Created system user: {username}")
    
    result = run(f"pdbedit -L {safe_username}", check=False)
    if result.returncode != 0:
        run(
            f"(echo {shlex.quote(password)}; echo {shlex.quote(password)}) | smbpasswd -a -s {safe_username}",
            display_cmd=f"(echo [REDACTED]; echo [REDACTED]) | smbpasswd -a -s {safe_username}"
        )
        print(f"  Created Samba user: {username}")
    else:
        run(
            f"(echo {shlex.quote(password)}; echo {shlex.quote(password)}) | smbpasswd -s {safe_username}",
            display_cmd=f"(echo [REDACTED]; echo [REDACTED]) | smbpasswd -s {safe_username}"
        )
        print(f"  Updated Samba user password: {username}")
    
    run(f"smbpasswd -e {safe_username}", check=False)


def _get_veto_dirs_for_share(share_path: str, config: SetupConfig) -> list[str]:
    """Determine which internal directories should be hidden from a Samba share.
    
    Checks scrub specs to find database directories that are subdirectories of
    the share path. These should be hidden from Samba clients via veto files.
    
    Args:
        share_path: The primary path of the Samba share
        config: SetupConfig with scrub_specs
        
    Returns:
        List of directory basenames to veto (e.g. ['.pardatabase'])
    """
    veto_dirs: list[str] = []
    
    if not config.scrub_specs:
        return veto_dirs
    
    normalized_share = os.path.normpath(share_path)
    
    for spec in config.scrub_specs:
        if len(spec) < 2:
            continue
        scrub_dir = os.path.normpath(spec[0])
        db_path = spec[1]
        
        # Only relevant if the scrub directory matches or is under the share path
        if scrub_dir != normalized_share and not scrub_dir.startswith(normalized_share + '/'):
            continue
        
        # Resolve relative database path against the scrub directory
        if not db_path.startswith('/'):
            resolved_db = os.path.normpath(os.path.join(scrub_dir, db_path))
        else:
            resolved_db = os.path.normpath(db_path)
        
        # Check if the resolved database path is under the share path
        if resolved_db.startswith(normalized_share + '/'):
            # Extract the directory basename relative to share
            relative = os.path.relpath(resolved_db, normalized_share)
            # Only veto top-level directories within the share
            top_level = relative.split('/')[0]
            if top_level and top_level not in veto_dirs:
                veto_dirs.append(top_level)
    
    return veto_dirs


def setup_samba_share(config: SetupConfig, share_spec: Optional[list[str]] = None, **_ : Any) -> None:
    share_config = parse_share_spec(
        share_spec,
        parse_share_credentials(config.share_credentials)
    )

    share_name = share_config['share_name']
    access_type = share_config['access_type']
    paths = share_config['paths']
    users = share_config['users']

    if not paths:
        raise ValueError(f"No paths specified for share: {share_name}")

    if not users:
        raise ValueError(f"No users specified for share: {share_name}")

    primary_path = paths[0]

    for path in paths:
        if is_path_under_mnt(path):
            mount_ancestor = get_mount_ancestor(path)
            if not mount_ancestor:
                raise RuntimeError(
                    f"Share path {path} is under /mnt but no mounted filesystem found. "
                    f"Is the drive mounted?"
                )
        os.makedirs(path, exist_ok=True)

    if len(paths) > 1:
        print(f"  Note: Multiple paths provided, configuring primary path {primary_path} in Samba")
        print(f"  All paths will have permissions set: {', '.join(paths)}")
    else:
        print(f"  Ensured path exists: {primary_path}")

    group_name = f"smb_{share_name}_{access_type}"
    safe_group = shlex.quote(group_name)

    result = run(f"getent group {safe_group}", check=False)
    if result.returncode != 0:
        run(f"groupadd {safe_group}")
        print(f"  Created group: {group_name}")

    for user_info in users:
        username = user_info['username']
        password = user_info['password']
        safe_username = shlex.quote(username)

        create_samba_user(username, password)
        run(f"usermod -aG {safe_group} {safe_username}")
        print(f"  Added {username} to group {group_name}")

    for path in paths:
        safe_path_iter = shlex.quote(path)
        run(f"chgrp -R {safe_group} {safe_path_iter}")

        if access_type == "write":
            run(f"chmod -R 2775 {safe_path_iter}")
        else:
            run(f"chmod -R 2755 {safe_path_iter}")

    print(f"  Set {'write' if access_type == 'write' else 'read-only'} permissions on {len(paths)} path(s)")

    smb_conf = "/etc/samba/smb.conf"
    section_marker = f"[{share_name}_{access_type}]"

    share_lines = [
        section_marker,
        f"   comment = {share_name} ({access_type})",
        f"   path = {primary_path}",
        f"   valid users = @{group_name}",
        "   browseable = yes",
        f"   read only = {'yes' if access_type == 'read' else 'no'}",
    ]

    if access_type == "write":
        share_lines.append(f"   write list = @{group_name}")

    share_lines.extend([
        f"   create mask = {'0644' if access_type == 'read' else '0664'}",
        f"   directory mask = {'0755' if access_type == 'read' else '0775'}",
        f"   force group = {group_name}",
    ])

    # Veto internal directories that should not be visible to Samba clients.
    # Detect scrub database directories that fall within this share's path.
    veto_dirs = _get_veto_dirs_for_share(primary_path, config)
    if veto_dirs:
        # Samba's `veto files` syntax uses the first character as the
        # separator and matches against the on-disk filename verbatim
        # (with `*`/`?` globbing). Use the actual directory names from
        # disk; do not synthesise a leading dot, which would otherwise
        # make patterns like `.subdir` fail to match a directory named
        # `subdir`.
        veto_pattern = "/" + "/".join(veto_dirs) + "/"
        share_lines.append(f"   veto files = {veto_pattern}")
        share_lines.append("   delete veto files = no")
        print(f"  Hiding internal directories from share: {', '.join(veto_dirs)}")

    desired_section = "\n" + "\n".join(share_lines) + "\n"

    if not os.path.exists(smb_conf):
        run(f"touch {smb_conf}")

    with open(smb_conf, 'r') as f:
        content = f.read()

    pattern = re.compile(r"(?ms)^\s*" + re.escape(section_marker) + r".*?(?=^\s*\[|\Z)")

    if not pattern.search(content):
        with open(smb_conf, 'a') as f:
            f.write(desired_section)
        print(f"  Added share configuration: {share_name}_{access_type}")
    else:
        new_content = pattern.sub(desired_section.strip() + "\n", content)
        if new_content != content:
            with open(smb_conf, 'w') as f:
                f.write(new_content)
            print(f"  Updated share configuration: {share_name}_{access_type}")
        else:
            print(f"  Share configuration already exists: {share_name}_{access_type}")

    result = run("testparm -s", check=False, capture_output=True)
    if result.returncode != 0:
        print("  ✗ Samba configuration has errors, skipping reload")
        if result.stderr:
            print(f"  Error: {result.stderr[:200]}")
        print("  Fix the configuration and run 'systemctl reload smbd' manually")
        return

    run("systemctl reload smbd")
    print(f"  ✓ Share configured: {share_name}_{access_type} -> {primary_path}")


SAMBA_GLOBAL_HARDENED_SETTINGS: dict[str, str] = {
    # Pin to SMB3+ everywhere. SMB2 is allowed only by Vista/Server 2008.
    # Modern Linux kernels, macOS, and Windows 7+ all speak SMB3.
    "server min protocol": "SMB3",
    "client min protocol": "SMB3",
    # Mandate signing and encryption to prevent tampering / sniffing on
    # the wire. Both are SMB3 features and should "just work" against
    # current Linux/macOS/Windows clients.
    "server signing": "mandatory",
    "client signing": "mandatory",
    "smb encrypt": "required",
    # Disable the legacy NetBIOS-over-TCP transport entirely; modern SMB
    # only uses 445/tcp. This also prevents nmbd from binding 137/138/139.
    "disable netbios": "yes",
    "workgroup": "WORKGROUP",
    "server string": "Samba Server",
    # Per-machine log files following the upstream `log.%m` template so
    # that the fail2ban `log.*` glob actually catches them; the previous
    # `%m.log` template produced names like `BUILDPC.log` that the glob
    # would not match.
    "log file": "/var/log/samba/log.%m",
    "max log size": "50",
    "log level": "1 auth:3",
    "security": "user",
    "map to guest": "Never",
    "guest account": "nobody",
    "restrict anonymous": "2",
    "obey pam restrictions": "yes",
    "unix password sync": "yes",
    "pam password change": "yes",
}


# Modern smbd (4.x) emits a single structured "Auth:" line for every
# authentication attempt that includes both the NT_STATUS_* result and
# `remote host [ipv4:<addr>:<port>]` / `[ipv6:[<addr>]:<port>]`. The
# filter targets only failure statuses so successful logins are not
# counted toward the ban threshold.
SAMBA_FAIL2BAN_FILTER = """[INCLUDES]
before = common.conf

[Definition]
_daemon = smbd
failregex = ^.*Auth: .*status \\[NT_STATUS_(?:WRONG_PASSWORD|NO_SUCH_USER|ACCOUNT_(?:DISABLED|LOCKED_OUT|RESTRICTION)|LOGON_FAILURE|ACCESS_DENIED)\\].*remote host \\[ipv[46]:?<HOST>(?::\\d+)?\\]
ignoreregex =

[Init]
journalmatch = _SYSTEMD_UNIT=smbd.service
"""


# 445/tcp only — port 139 is no longer opened by configure_samba_firewall
# and `disable netbios = yes` keeps nmbd from binding the legacy ports.
SAMBA_FAIL2BAN_JAIL = """[samba-auth]
enabled = true
port = 445
protocol = tcp
filter = samba-auth
logpath = /var/log/samba/log.smbd
          /var/log/samba/log.*
backend = auto
maxretry = 5
bantime = 3600
findtime = 600
"""


def configure_samba_global_settings(config: SetupConfig) -> None:
    smb_conf = "/etc/samba/smb.conf"

    settings = SAMBA_GLOBAL_HARDENED_SETTINGS
    
    if not os.path.exists(smb_conf):
        run("touch /etc/samba/smb.conf")
    
    with open(smb_conf, 'r') as f:
        content = f.read()
    
    global_section_exists = "[global]" in content
    
    if not global_section_exists:
        global_config = "[global]\n"
        for key, value in settings.items():
            global_config += f"   {key} = {value}\n"
        
        with open(smb_conf, 'w') as f:
            f.write(global_config + "\n" + content)
        
        print("  ✓ Added global Samba configuration with security hardening")
    else:
        updated = False
        for key, value in settings.items():
            pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=.*$", re.MULTILINE)
            if pattern.search(content):
                new_content = pattern.sub(f"   {key} = {value}", content)
                if new_content != content:
                    content = new_content
                    updated = True
            else:
                global_pattern = re.compile(r"(\[global\])", re.IGNORECASE)
                content = global_pattern.sub(f"\\1\n   {key} = {value}", content, count=1)
                updated = True
        
        if updated:
            with open(smb_conf, 'w') as f:
                f.write(content)
            print("  ✓ Updated global Samba configuration with security hardening")
        else:
            print("  ✓ Global Samba configuration already up to date")



def configure_samba_fail2ban(config: SetupConfig) -> None:
    from lib.remote_utils import is_service_active

    jail_path = "/etc/fail2ban/jail.d/samba-auth.local"
    filter_path = "/etc/fail2ban/filter.d/samba-auth.conf"

    # Older versions of this tool wrote /etc/fail2ban/jail.d/samba.local and
    # /etc/fail2ban/filter.d/samba.conf. The latter clobbered the distro
    # filter shipped by the fail2ban package (a dpkg conffile), which is
    # both rude and confusing on upgrades. Remove the legacy files so the
    # distro-shipped samba filter is restored on next package install.
    legacy_files = [
        "/etc/fail2ban/jail.d/samba.local",
        "/etc/fail2ban/filter.d/samba.conf",
    ]
    for path in legacy_files:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    if os.path.exists(jail_path):
        if is_service_active("fail2ban"):
            print("  ✓ fail2ban for Samba already configured")
            return

    if not is_package_installed("fail2ban"):
        run("apt-get install -y -qq fail2ban")

    # Modern smbd (4.x) emits a single structured "Auth:" line for every
    # authentication attempt that includes both the NT_STATUS_* result and
    # `remote host [ipv4:<addr>:<port>]` / `[ipv6:[<addr>]:<port>]`. The
    # filter targets only failure statuses so successful logins are not
    # counted toward the ban threshold.
    fail2ban_samba_filter = SAMBA_FAIL2BAN_FILTER

    # 445/tcp only — port 139 is no longer opened by configure_samba_firewall
    # and `disable netbios = yes` keeps nmbd from binding the legacy ports.
    fail2ban_samba_jail = SAMBA_FAIL2BAN_JAIL

    os.makedirs("/etc/fail2ban/filter.d", exist_ok=True)
    os.makedirs("/etc/fail2ban/jail.d", exist_ok=True)

    with open(filter_path, "w") as f:
        f.write(fail2ban_samba_filter)

    with open(jail_path, "w") as f:
        f.write(fail2ban_samba_jail)

    run("systemctl enable fail2ban", check=False)
    run("systemctl restart fail2ban")

    print("  ✓ fail2ban configured for Samba (5 failed attempts = 1 hour ban)")
