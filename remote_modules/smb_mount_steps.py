"""SMB/CIFS mount configuration with systemd."""

import os
import shlex
from typing import List

from lib.config import SetupConfig
from .utils import run


def parse_smb_mount_spec(mount_spec: List[str]) -> dict:
    """Parse SMB mount specification.
    
    Args:
        mount_spec: [mountpoint, ip, credentials, share, subdir]
        
    Returns:
        dict with mount configuration
    """
    if len(mount_spec) != 5:
        raise ValueError(f"Invalid SMB mount spec: expected 5 arguments, got {len(mount_spec)}")
    
    mountpoint, ip, credentials, share, subdir = mount_spec
    
    if not mountpoint.startswith('/'):
        raise ValueError(f"Mountpoint must be absolute: {mountpoint}")
    
    if ':' not in credentials:
        raise ValueError(f"Credentials must be username:password format")
    
    username, password = credentials.split(':', 1)
    
    return {
        'mountpoint': mountpoint,
        'ip': ip,
        'username': username,
        'password': password,
        'share': share,
        'subdir': subdir
    }


def configure_smb_mount(config: SetupConfig, mount_spec: List[str] = None, **_) -> None:
    """Configure persistent SMB mount using systemd.
    
    Args:
        config: SetupConfig object
        mount_spec: [mountpoint, ip, credentials, share, subdir]
    """
    mount_config = parse_smb_mount_spec(mount_spec)
    
    mountpoint = mount_config['mountpoint']
    ip = mount_config['ip']
    username = mount_config['username']
    password = mount_config['password']
    share = mount_config['share']
    subdir = mount_config['subdir']
    
    os.makedirs(mountpoint, exist_ok=True)
    run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(mountpoint)}")
    
    credentials_dir = "/root/.smb"
    os.makedirs(credentials_dir, exist_ok=True)
    run(f"chmod 700 {shlex.quote(credentials_dir)}")
    
    # Use systemd-escape to generate proper unit name
    result = run(f"systemd-escape -p {shlex.quote(mountpoint)}", capture_output=True, text=True)
    escaped_mountpoint = result.stdout.strip()
    unit_name = f"{escaped_mountpoint}.mount"
    unit_path = f"/etc/systemd/system/{unit_name}"
    
    # Create safe filename for credentials
    safe_mountpoint = mountpoint.replace('/', '_').strip('_')
    creds_file = f"{credentials_dir}/credentials-{safe_mountpoint}"
    
    creds_content = f"""username={username}
password={password}
"""
    
    with open(creds_file, 'w') as f:
        f.write(creds_content)
    run(f"chmod 600 {shlex.quote(creds_file)}")
    
    # Validate and sanitize inputs
    if not ip.replace('.', '').replace(':', '').isalnum():
        raise ValueError(f"Invalid IP address format: {ip}")
    if '/' in share or '\\' in share or ' ' in share:
        raise ValueError(f"Invalid share name (cannot contain /, \\, or spaces): {share}")
    if subdir and not subdir.startswith('/'):
        raise ValueError(f"Subdirectory must start with /: {subdir}")
    
    unc_path = f"//{ip}/{share}{subdir}"
    
    def _escape_systemd_description(value: str) -> str:
        """Escape value for safe use in a systemd Description field."""
        return value.replace("\\", "\\\\").replace("\n", " ").replace('"', "'")
    
    escaped_desc = _escape_systemd_description(mountpoint)
    
    unit_content = f"""[Unit]
Description=SMB mount for {escaped_desc}
After=network-online.target
Wants=network-online.target

[Mount]
What={unc_path}
Where={mountpoint}
Type=cifs
Options=credentials={creds_file},uid={config.username},gid={config.username},file_mode=0755,dir_mode=0755,nofail,x-systemd.automount,x-systemd.idle-timeout=60

[Install]
WantedBy=multi-user.target
"""
    
    with open(unit_path, 'w') as f:
        f.write(unit_content)
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(unit_name)}")
    
    result = run(f"systemctl start {shlex.quote(unit_name)}", check=False)
    if result.returncode == 0:
        print(f"  ✓ SMB mount configured and mounted: {mountpoint} → {unc_path}")
    else:
        print(f"  ✓ SMB mount configured: {mountpoint} → {unc_path} (will mount at boot)")



