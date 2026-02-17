"""Remote deployment utilities for pushing builds to app servers."""

from __future__ import annotations

import os
import json
import subprocess
import shlex
import tempfile
from typing import Optional

from lib.types import JSONDict


def load_deploy_targets() -> dict[str, JSONDict]:
    """Load deploy targets configuration."""
    targets_file = "/etc/infra_tools/cicd/deploy_targets.json"
    
    if not os.path.exists(targets_file):
        return {}
    
    try:
        with open(targets_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_deploy_target(target_host: str) -> Optional[JSONDict]:
    """Get configuration for a specific deploy target."""
    targets = load_deploy_targets()
    return targets.get(target_host)


def _build_ssh_cmd(target: JSONDict, remote_cmd: str) -> list[str]:
    """Build SSH command for a target."""
    ssh_key = target.get('ssh_key', '/var/lib/infra_tools/cicd/.ssh/deploy_key')
    ssh_port = target.get('ssh_port', 22)
    user = target.get('user', 'deploy')
    host = target['host']
    
    return [
        'ssh',
        '-i', ssh_key,
        '-p', str(ssh_port),
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=30',
        f'{user}@{host}',
        remote_cmd
    ]


def push_artifact(
    local_path: str,
    target_host: str,
    remote_path: str,
    exclude_patterns: Optional[list[str]] = None
) -> bool:
    """Push artifact directory to remote server using rsync."""
    target = get_deploy_target(target_host)
    if not target:
        print(f"  ✗ Unknown deploy target: {target_host}")
        return False
    
    ssh_key = target.get('ssh_key', '/var/lib/infra_tools/cicd/.ssh/deploy_key')
    ssh_port = target.get('ssh_port', 22)
    user = target.get('user', 'deploy')
    host = target['host']
    
    rsync_cmd = [
        'rsync', '-avz', '--delete',
        '-e', f'ssh -i {shlex.quote(ssh_key)} -p {ssh_port} -o StrictHostKeyChecking=accept-new -o BatchMode=yes'
    ]
    
    if exclude_patterns:
        for pattern in exclude_patterns:
            rsync_cmd.extend(['--exclude', pattern])
    
    if not local_path.endswith('/'):
        local_path = local_path + '/'
    
    remote_target = f"{user}@{host}:{remote_path}"
    rsync_cmd.extend([local_path, remote_target])
    
    try:
        result = subprocess.run(
            rsync_cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode != 0:
            print(f"  ✗ rsync failed: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ rsync timed out")
        return False
    except Exception as e:
        print(f"  ✗ rsync error: {e}")
        return False


def push_nginx_config(config_content: str, target_host: str, domain: str) -> bool:
    """Push nginx configuration to remote server."""
    target = get_deploy_target(target_host)
    if not target:
        print(f"  ✗ Unknown deploy target: {target_host}")
        return False
    
    config_name = domain.replace('.', '_')
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
        f.write(config_content)
        temp_path = f.name
    
    try:
        ssh_key = target.get('ssh_key', '/var/lib/infra_tools/cicd/.ssh/deploy_key')
        ssh_port = target.get('ssh_port', 22)
        user = target.get('user', 'deploy')
        host = target['host']
        
        scp_cmd = [
            'scp',
            '-i', ssh_key,
            '-P', str(ssh_port),
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'BatchMode=yes',
            temp_path,
            f"{user}@{host}:/tmp/{config_name}.conf"
        ]
        
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to upload nginx config: {result.stderr}")
            return False
        
        remote_cmd = f"sudo mkdir -p /etc/nginx/sites-available && sudo mv /tmp/{config_name}.conf /etc/nginx/sites-available/{config_name} && sudo ln -sf /etc/nginx/sites-available/{config_name} /etc/nginx/sites-enabled/{config_name}"
        
        ssh_cmd = _build_ssh_cmd(target, remote_cmd)
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to install nginx config: {result.stderr}")
            return False
        
        return True
    finally:
        os.unlink(temp_path)


def reload_nginx(target_host: str) -> bool:
    """Reload nginx on remote server."""
    target = get_deploy_target(target_host)
    if not target:
        return False
    
    remote_cmd = "sudo nginx -t && sudo systemctl reload nginx"
    ssh_cmd = _build_ssh_cmd(target, remote_cmd)
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to reload nginx: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ SSH timed out")
        return False


def restart_service(target_host: str, service_name: str) -> bool:
    """Restart a systemd service on remote server."""
    target = get_deploy_target(target_host)
    if not target:
        return False
    
    remote_cmd = f"sudo systemctl restart {shlex.quote(service_name)}"
    ssh_cmd = _build_ssh_cmd(target, remote_cmd)
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to restart {service_name}: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ SSH timed out")
        return False


def remove_deployment(target_host: str, deploy_path: str, domain: Optional[str] = None) -> bool:
    """Remove a deployment from remote server."""
    target = get_deploy_target(target_host)
    if not target:
        return False
    
    cmds = [f"sudo rm -rf {shlex.quote(deploy_path)}"]
    
    if domain:
        config_name = domain.replace('.', '_')
        cmds.append(f"sudo rm -f /etc/nginx/sites-enabled/{config_name}")
        cmds.append(f"sudo rm -f /etc/nginx/sites-available/{config_name}")
    
    remote_cmd = " && ".join(cmds)
    ssh_cmd = _build_ssh_cmd(target, remote_cmd)
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to remove deployment: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ SSH timed out")
        return False


def test_deploy_connection(target_host: str) -> bool:
    """Test SSH connection to deploy target."""
    target = get_deploy_target(target_host)
    if not target:
        print(f"  ✗ Unknown deploy target: {target_host}")
        return False
    
    ssh_cmd = _build_ssh_cmd(target, "echo 'connection ok'")
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"  ✗ Connection failed: {result.stderr}")
            return False
        print(f"  ✓ Connection to {target_host} successful")
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ Connection timed out")
        return False