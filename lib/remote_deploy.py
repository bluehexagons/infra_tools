"""Remote deployment utilities for pushing builds to app servers."""

from __future__ import annotations

import os
import json
import subprocess
import shlex
import tempfile
from typing import Optional

from lib.ssh_utils import build_scp_command, build_ssh_command, build_rsync_ssh_transport, chain_remote_commands, shell_join
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

    return build_ssh_command(
        host,
        user,
        ssh_key,
        port=ssh_port,
        remote_command=remote_cmd,
        batch_mode=True,
        connect_timeout=30,
        server_alive_interval=None,
    )


def _build_ssh_stdin_script_cmd(target: JSONDict, working_dir: str) -> list[str]:
    """Build an SSH command that executes a bash script streamed over stdin."""

    remote_cmd = chain_remote_commands(
        [
            ["cd", working_dir],
            ["bash", "-s", "--"],
        ]
    )
    return _build_ssh_cmd(target, remote_cmd)


def push_artifact(
    local_path: str,
    target_host: str,
    remote_path: str,
    exclude_patterns: Optional[list[str]] = None
) -> bool:
    """Push artifact directory to remote server using rsync.
    
    Security Note: Uses StrictHostKeyChecking=accept-new which accepts new host keys
    without verification on first connection. This is vulnerable to MITM attacks during
    first connection. For production, consider using ssh-keyscan during setup to
    populate known_hosts, or manually verify host keys before first deployment.
    """
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
        '-e', build_rsync_ssh_transport(ssh_key=ssh_key, port=ssh_port, batch_mode=True, connect_timeout=30),
    ]
    
    if exclude_patterns:
        for pattern in exclude_patterns:
            rsync_cmd.extend(['--exclude', pattern])
    
    if not local_path.endswith('/'):
        local_path = local_path + '/'
    
    remote_target = f"{user}@{host}:{shlex.quote(remote_path)}"
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
        
        remote_temp_path = f"/tmp/{config_name}.conf"
        scp_cmd = build_scp_command(
            host,
            user,
            temp_path,
            remote_temp_path,
            ssh_key,
            port=ssh_port,
            batch_mode=True,
            connect_timeout=30,
        )
        
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ✗ Failed to upload nginx config: {result.stderr}")
            return False
        
        remote_cmd = chain_remote_commands(
            [
                ["sudo", "mkdir", "-p", "/etc/nginx/sites-available"],
                ["sudo", "mv", remote_temp_path, f"/etc/nginx/sites-available/{config_name}"],
                [
                    "sudo",
                    "ln",
                    "-sf",
                    f"/etc/nginx/sites-available/{config_name}",
                    f"/etc/nginx/sites-enabled/{config_name}",
                ],
            ]
        )
        
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
    
    remote_cmd = chain_remote_commands(
        [
            ["sudo", "nginx", "-t"],
            ["sudo", "systemctl", "reload", "nginx"],
        ]
    )
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
    
    remote_cmd = shell_join(["sudo", "systemctl", "restart", service_name])
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
    
    cmds: list[list[str]] = [["sudo", "rm", "-rf", deploy_path]]
    
    if domain:
        config_name = domain.replace('.', '_')
        cmds.append(["sudo", "rm", "-f", f"/etc/nginx/sites-enabled/{config_name}"])
        cmds.append(["sudo", "rm", "-f", f"/etc/nginx/sites-available/{config_name}"])

    remote_cmd = chain_remote_commands(cmds)
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
    
    ssh_cmd = _build_ssh_cmd(target, shell_join(["echo", "connection ok"]))
    
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
