"""Build server setup steps for deploying to app servers."""

from __future__ import annotations

import os
import json
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed


def generate_deploy_ssh_key(config: SetupConfig) -> None:
    """Generate SSH key for deploying to app servers."""
    ssh_dir = "/var/lib/infra_tools/cicd/.ssh"
    key_file = f"{ssh_dir}/deploy_key"
    
    if os.path.exists(key_file):
        print("  ✓ Deploy SSH key already exists")
        return
    
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    
    run(f"ssh-keygen -t ed25519 -f {key_file} -N '' -C 'deploy@build-server'")
    
    run(f"chown -R webhook:webhook {ssh_dir}")
    run(f"chmod 700 {ssh_dir}")
    run(f"chmod 600 {key_file}")
    run(f"chmod 644 {key_file}.pub")
    
    print("  ✓ Generated deploy SSH key")
    print(f"  ℹ Public key at: {key_file}.pub")
    print("  ℹ Add this key to app servers' /home/deploy/.ssh/authorized_keys")


def configure_deploy_targets(config: SetupConfig) -> None:
    """Configure deploy targets (app servers) for remote deployment."""
    if not config.deploy_targets:
        print("  ℹ No deploy targets specified")
        return
    
    targets_file = "/etc/infra_tools/cicd/deploy_targets.json"
    os.makedirs(os.path.dirname(targets_file), exist_ok=True)
    
    existing_targets = {}
    if os.path.exists(targets_file):
        try:
            with open(targets_file, 'r') as f:
                existing_targets = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    
    for target_host in config.deploy_targets:
        existing_targets[target_host] = {
            "host": target_host,
            "user": "deploy",
            "ssh_port": 22,
            "base_dir": "/var/www",
            "ssh_key": "/var/lib/infra_tools/cicd/.ssh/deploy_key",
        }
    
    with open(targets_file, 'w') as f:
        json.dump(existing_targets, f, indent=2)
    
    os.chmod(targets_file, 0o644)
    
    print(f"  ✓ Configured {len(config.deploy_targets)} deploy target(s)")
    for target in config.deploy_targets:
        print(f"    - {target}")


def configure_deploy_known_hosts(config: SetupConfig) -> None:
    """Add deploy targets to known_hosts for non-interactive SSH."""
    if not config.deploy_targets:
        print("  ℹ No deploy targets to add to known_hosts")
        return
    
    ssh_dir = "/var/lib/infra_tools/cicd/.ssh"
    known_hosts = f"{ssh_dir}/known_hosts"
    
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    
    for target_host in config.deploy_targets:
        result = run(
            f"ssh-keyscan -H {shlex.quote(target_host)} 2>/dev/null",
            capture_output=True,
            check=False
        )
        if result.returncode == 0 and result.stdout:
            with open(known_hosts, 'a') as f:
                f.write(result.stdout)
    
    if os.path.exists(known_hosts):
        run(f"chown webhook:webhook {known_hosts}")
        run(f"chmod 644 {known_hosts}")
    
    print("  ✓ Added deploy targets to known_hosts")


def create_build_workspace_dirs(config: SetupConfig) -> None:
    """Create workspace directories for builds and artifacts."""
    directories = [
        "/var/lib/infra_tools/cicd/workspaces",
        "/var/lib/infra_tools/cicd/artifacts",
        "/var/lib/infra_tools/cicd/logs",
        "/var/lib/infra_tools/cicd/jobs",
    ]
    
    for directory in directories:
        os.makedirs(directory, mode=0o755, exist_ok=True)
    
    run("chown -R webhook:webhook /var/lib/infra_tools/cicd")
    run("chmod -R 750 /var/lib/infra_tools/cicd")
    
    print("  ✓ Created build workspace directories")


def install_build_dependencies(config: SetupConfig) -> None:
    """Install common build dependencies."""
    packages = ['git', 'rsync', 'openssh-client']
    
    missing = [pkg for pkg in packages if not is_package_installed(pkg)]
    
    if not missing:
        print("  ✓ Build dependencies already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(f"apt-get install -y -qq {' '.join(missing)}")
    
    print("  ✓ Build dependencies installed")