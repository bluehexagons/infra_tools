import os
import shlex
from typing import List, Dict, Optional

from .utils import run, is_package_installed, file_contains


def install_samba(os_type: str, **_) -> None:
    if is_package_installed("samba", os_type):
        print("  ✓ Samba already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get update -qq")
    run("apt-get install -y -qq samba samba-common-bin")
    
    run("systemctl enable smbd")
    run("systemctl start smbd")
    
    print("  ✓ Samba installed and service started")


def configure_samba_firewall(os_type: str, **_) -> None:
    rules = [
        "ufw allow 139/tcp comment 'Samba NetBIOS'",
        "ufw allow 445/tcp comment 'Samba SMB'",
    ]
    
    for rule in rules:
        result = run(rule, check=False)
        if result.returncode != 0:
            print(f"  Warning: Failed to add firewall rule: {rule}")
    
    run("ufw reload", check=False)
    print("  ✓ Firewall configured for Samba")


def parse_share_spec(share_spec: List[str]) -> Dict:
    if len(share_spec) < 4:
        raise ValueError("Share spec requires: access_type share_name paths users")
    
    access_type = share_spec[0]
    if access_type not in ["read", "write"]:
        raise ValueError(f"Invalid access type: {access_type}. Must be 'read' or 'write'")
    
    share_name = share_spec[1]
    paths_str = share_spec[2]
    users_str = share_spec[3]
    
    paths = [p.strip() for p in paths_str.split(',') if p.strip()]
    
    users = []
    for user_spec in users_str.split(','):
        user_spec = user_spec.strip()
        if not user_spec:
            continue
        if ':' not in user_spec:
            raise ValueError(f"Invalid user spec: {user_spec}. Must be 'username:password'")
        username, password = user_spec.split(':', 1)
        users.append({'username': username.strip(), 'password': password.strip()})
    
    return {
        'access_type': access_type,
        'share_name': share_name,
        'paths': paths,
        'users': users
    }


def create_samba_user(username: str, password: str) -> None:
    safe_username = shlex.quote(username)
    
    result = run(f"id {safe_username}", check=False)
    if result.returncode != 0:
        run(f"useradd -M -s /usr/sbin/nologin {safe_username}")
        print(f"  Created system user: {username}")
    
    result = run(f"pdbedit -L {safe_username}", check=False)
    if result.returncode != 0:
        run(f"(echo {shlex.quote(password)}; echo {shlex.quote(password)}) | smbpasswd -a -s {safe_username}")
        print(f"  Created Samba user: {username}")
    else:
        run(f"(echo {shlex.quote(password)}; echo {shlex.quote(password)}) | smbpasswd -s {safe_username}")
        print(f"  Updated Samba user password: {username}")
    
    run(f"smbpasswd -e {safe_username}", check=False)


def setup_samba_share(share_spec: List[str], **_) -> None:
    config = parse_share_spec(share_spec)
    
    share_name = config['share_name']
    access_type = config['access_type']
    paths = config['paths']
    users = config['users']
    
    if not paths:
        raise ValueError(f"No paths specified for share: {share_name}")
    
    if not users:
        raise ValueError(f"No users specified for share: {share_name}")
    
    primary_path = paths[0]
    safe_path = shlex.quote(primary_path)
    
    for path in paths:
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
    
    config_exists = False
    if os.path.exists(smb_conf):
        with open(smb_conf, 'r') as f:
            config_exists = section_marker in f.read()
    
    if not config_exists:
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
        
        share_config = "\n" + "\n".join(share_lines) + "\n"
        
        with open(smb_conf, 'a') as f:
            f.write(share_config)
        
        print(f"  Added share configuration: {share_name}_{access_type}")
    else:
        print(f"  Share configuration already exists: {share_name}_{access_type}")
    
    result = run("testparm -s", check=False)
    if result.returncode != 0:
        print("  Warning: Samba configuration may have errors")
    
    run("systemctl reload smbd")
    print(f"  ✓ Share configured: {share_name}_{access_type} -> {primary_path}")


def configure_samba_global_settings(**_) -> None:
    smb_conf = "/etc/samba/smb.conf"
    
    settings = {
        "server min protocol": "SMB2",
        "client min protocol": "SMB2",
        "workgroup": "WORKGROUP",
        "server string": "Samba Server",
        "log file": "/var/log/samba/%m.log",
        "max log size": "50",
        "log level": "1 auth:3",
        "security": "user",
        "map to guest": "Never",
        "guest account": "nobody",
        "restrict anonymous": "2",
        "null passwords": "no",
        "obey pam restrictions": "yes",
        "unix password sync": "yes",
        "pam password change": "yes",
    }
    
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
        print("  ✓ Global Samba configuration already exists")


def configure_samba_fail2ban(**_) -> None:
    from .utils import is_service_active
    
    if os.path.exists("/etc/fail2ban/jail.d/samba.local"):
        if is_service_active("fail2ban"):
            print("  ✓ fail2ban for Samba already configured")
            return
    
    if not is_package_installed("fail2ban", "debian"):
        run("apt-get install -y -qq fail2ban")
    
    fail2ban_samba_filter = """[Definition]
failregex = ^.*smbd.*: .*Authentication for user .* from <HOST>.*FAILED.*$
            ^.*smbd.*: .*Failed password for .* from <HOST>.*$
            ^.*smbd.*: .*check_ntlm_password:  Authentication for user .* failed with NT_STATUS_WRONG_PASSWORD.*$
ignoreregex =
"""
    
    fail2ban_samba_jail = """[samba]
enabled = true
port = 139,445
protocol = tcp
filter = samba
logpath = /var/log/samba/log.smbd
          /var/log/samba/log.*
maxretry = 5
bantime = 3600
findtime = 600
"""
    
    os.makedirs("/etc/fail2ban/filter.d", exist_ok=True)
    os.makedirs("/etc/fail2ban/jail.d", exist_ok=True)
    
    with open("/etc/fail2ban/filter.d/samba.conf", "w") as f:
        f.write(fail2ban_samba_filter)
    
    with open("/etc/fail2ban/jail.d/samba.local", "w") as f:
        f.write(fail2ban_samba_jail)
    
    run("systemctl enable fail2ban", check=False)
    run("systemctl restart fail2ban")
    
    print("  ✓ fail2ban configured for Samba (5 failed attempts = 1 hour ban)")

