"""SMB/CIFS mount configuration with systemd."""

from __future__ import annotations
import os
import shlex
from typing import Any, Optional

from lib.config import SetupConfig
from lib.remote_utils import run
from lib.systemd_service import cleanup_systemd_unit
from lib.validation import validate_smb_mount_specs


def parse_smb_mount_spec(mount_spec: Optional[list[str]]) -> dict[str, Any]:
    """Parse SMB mount specification.
    
    Args:
        mount_spec: [mountpoint, ip, credentials, share, subdir]
        
    Returns:
        dict with mount configuration
    """
    if not mount_spec:
        raise ValueError("mount_spec is required")
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


def configure_smb_mount(config: SetupConfig, mount_spec: Optional[list[str]] = None, **_ : Any) -> None:
    """Configure persistent SMB mount using systemd.
    
    Args:
        config: SetupConfig object
        mount_spec: [mountpoint, ip, credentials, share, subdir]
    """
    # Custom steps can call this directly, so apply the same complete
    # preflight used by the normal setup flow before changing the filesystem.
    validate_smb_mount_specs([mount_spec])
    mount_config = parse_smb_mount_spec(mount_spec)
    
    mountpoint = mount_config['mountpoint']
    ip = mount_config['ip']
    username = mount_config['username']
    password = mount_config['password']
    share = mount_config['share']
    subdir = mount_config['subdir']
    
    result = run(f"systemd-escape -p {shlex.quote(mountpoint)}", capture_output=True, text=True)
    escaped_mountpoint = result.stdout.strip()
    if not escaped_mountpoint or "/" in escaped_mountpoint:
        raise RuntimeError(f"Unable to derive a safe systemd unit name for mountpoint: {mountpoint}")

    unit_name = f"{escaped_mountpoint}.mount"
    unit_path = f"/etc/systemd/system/{unit_name}"

    os.makedirs(mountpoint, exist_ok=True)
    run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(mountpoint)}")

    credentials_dir = "/root/.smb"
    os.makedirs(credentials_dir, exist_ok=True)
    run(f"chmod 700 {shlex.quote(credentials_dir)}")

    # Use the already collision-resistant systemd-escaped mount name. The old
    # slash-to-underscore conversion made /mnt/a_b and /mnt/a/b share one
    # credential file and could silently point a mount at the wrong server.
    creds_file = f"{credentials_dir}/credentials-{escaped_mountpoint}"
    
    creds_content = f"""username={username}
password={password}
"""
    
    with open(creds_file, 'w') as f:
        f.write(creds_content)
    run(f"chown root:root {shlex.quote(creds_file)}")
    run(f"chmod 600 {shlex.quote(creds_file)}")
    
    unc_path = f"//{ip}/{share}{subdir}"
    
    def _escape_systemd_description(value: str) -> str:
        """Escape value for safe use in a systemd Description field."""
        return value.replace("\\", "\\\\").replace("\n", " ").replace('"', "'")
    
    escaped_desc = _escape_systemd_description(mountpoint)
    
    # Clean up existing mount unit before creating new one
    cleanup_systemd_unit(escaped_mountpoint, "mount")
    
    unit_content = f"""[Unit]
Description=SMB mount for {escaped_desc}
After=network-online.target
Wants=network-online.target

[Mount]
What={unc_path}
Where={mountpoint}
Type=cifs
Options=credentials={creds_file},uid={config.username},gid={config.username},file_mode=0644,dir_mode=0755,vers=3.0,seal,nofail,x-systemd.automount,x-systemd.idle-timeout=60

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

