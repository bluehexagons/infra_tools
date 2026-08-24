"""Build server setup steps for deploying to app servers."""

from __future__ import annotations

import os
import json

from common.common_steps import install_node_for_user, install_or_update_uv
from lib.atomic_io import write_json_atomic
from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed
from lib.ssh_enrollment import is_host_key_enrolled
from lib.workspace import get_known_hosts_path


CICD_USER = "webhook"
CICD_HOME = "/var/lib/infra_tools/cicd"


def generate_deploy_ssh_key(config: SetupConfig) -> None:
    """Generate SSH key for deploying to app servers."""
    ssh_dir = "/var/lib/infra_tools/cicd/.ssh"
    key_file = f"{ssh_dir}/deploy_key"
    
    if os.path.exists(key_file):
        print("  ✓ Deploy SSH key already exists")
        return
    
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    
    run([
        "ssh-keygen", "-t", "ed25519", "-f", key_file, "-N", "",
        "-C", "deploy@build-server",
    ])

    run(["chown", "-R", "webhook:webhook", ssh_dir])
    run(["chmod", "700", ssh_dir])
    run(["chmod", "600", key_file])
    run(["chmod", "644", f"{key_file}.pub"])
    
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
    
    write_json_atomic(targets_file, existing_targets, mode=0o644)
    
    print(f"  ✓ Configured {len(config.deploy_targets)} deploy target(s)")
    for target in config.deploy_targets:
        print(f"    - {target}")


def configure_deploy_known_hosts(config: SetupConfig) -> None:
    """Require explicitly enrolled deploy-target keys for non-interactive SSH."""
    if not config.deploy_targets:
        print("  ℹ No deploy targets to add to known_hosts")
        return
    
    workspace_dir = "/var/lib/infra_tools/cicd"
    known_hosts = get_known_hosts_path(workspace_dir)
    
    os.makedirs(os.path.dirname(known_hosts), mode=0o700, exist_ok=True)
    
    missing = [
        target_host
        for target_host in config.deploy_targets
        if not is_host_key_enrolled(
            target_host,
            known_hosts_path=known_hosts,
        )
    ]
    if missing:
        targets = ", ".join(missing)
        raise RuntimeError(
            "Deploy target host keys are not enrolled: "
            f"{targets}. Verify each fingerprint and run "
            "'sudo -n /usr/bin/python3 /opt/infra_tools/infra_tools.py "
            "--workspace /var/lib/infra_tools/cicd "
            "ssh-key enroll HOST' before enabling CI/CD deployment."
        )
    
    if os.path.exists(known_hosts):
        run(["chown", "webhook:webhook", known_hosts])
        run(["chmod", "644", known_hosts])
    
    print("  ✓ Verified explicitly enrolled deploy-target host keys")


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
    
    run(["chown", "-R", "webhook:webhook", "/var/lib/infra_tools/cicd"])
    run(["chmod", "-R", "750", "/var/lib/infra_tools/cicd"])
    
    print("  ✓ Created build workspace directories")


def install_build_node(config: SetupConfig) -> None:
    """Install nvm-managed Node.js for the CI/CD build user."""
    install_node_for_user(CICD_USER, CICD_HOME)


def install_build_python_tools(config: SetupConfig) -> None:
    """Install uv for the CI/CD build user."""
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(["apt-get", "install", "-y", "-qq", "python3", "python3-venv", "curl"])

    if install_or_update_uv(user_home=CICD_HOME, username=CICD_USER):
        print("  ✓ uv installed for build user")
    else:
        raise RuntimeError("uv installation failed for build user")


def install_build_dependencies(config: SetupConfig) -> None:
    """Install common build dependencies."""
    packages = ['git', 'rsync', 'openssh-client']
    
    def all_installed() -> bool:
        return all(is_package_installed(pkg) for pkg in packages)
    
    if all_installed():
        print("  ✓ Build dependencies already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(["apt-get", "install", "-y", "-qq", *packages])

    if all_installed():
        print("  ✓ Build dependencies installed")
        return
    raise RuntimeError("Build dependencies were not present after installation")
