"""App server setup steps for receiving deployments from build servers."""

from __future__ import annotations

import os
import shlex

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, is_service_active


def install_app_server_dependencies(config: SetupConfig) -> None:
    """Install minimal dependencies for app server."""
    packages = ['nginx', 'rsync']
    
    missing = [pkg for pkg in packages if not is_package_installed(pkg)]
    
    if not missing:
        print("  ✓ App server dependencies already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(f"apt-get install -y -qq {' '.join(missing)}")
    
    print("  ✓ App server dependencies installed")


def create_deploy_user(config: SetupConfig) -> None:
    """Create deploy user for receiving deployments from build server."""
    user = "deploy"
    
    result = run(f"id {user}", check=False)
    if result.returncode == 0:
        print("  ✓ Deploy user already exists")
        return
    
    run(f"useradd --system --create-home --shell /bin/bash {user}")
    
    ssh_dir = f"/home/{user}/.ssh"
    run(f"mkdir -p {ssh_dir}")
    run(f"chmod 700 {ssh_dir}")
    run(f"chown -R {user}:{user} {ssh_dir}")
    
    print("  ✓ Created deploy user")


def configure_deploy_sudoers(config: SetupConfig) -> None:
    """Configure sudoers for deploy user to manage nginx and services.
    
    Note: This allows deploy user to remove directories under /var/www/ but not
    the /var/www directory itself, limiting the blast radius of rm operations.
    Each deployment should be in its own subdirectory under /var/www/.
    """
    sudoers_file = "/etc/sudoers.d/deploy-nginx"
    
    if os.path.exists(sudoers_file):
        print("  ✓ Deploy sudoers already configured")
        return
    
    # Restrict rm operations to subdirectories only, not the entire /var/www
    sudoers_content = """# Allow deploy user to manage nginx and app services
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart nginx
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart rails-*
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart node-*
deploy ALL=(ALL) NOPASSWD: /bin/systemctl status rails-*
deploy ALL=(ALL) NOPASSWD: /bin/systemctl status node-*
deploy ALL=(ALL) NOPASSWD: /usr/bin/touch /var/log/infra_tools/*
deploy ALL=(ALL) NOPASSWD: /usr/bin/mkdir -p /var/www/*
# Restrict rm to subdirectories only (must have at least one path component after /var/www/)
deploy ALL=(ALL) NOPASSWD: /usr/bin/rm -rf /var/www/*/*
deploy ALL=(ALL) NOPASSWD: /bin/rm -rf /var/www/*/*
"""
    
    os.makedirs("/etc/sudoers.d", exist_ok=True)
    with open(sudoers_file, 'w') as f:
        f.write(sudoers_content)
    
    os.chmod(sudoers_file, 0o440)
    
    result = run("visudo -c", check=False)
    if result.returncode != 0:
        print("  ⚠ Sudoers validation failed, removing...")
        os.remove(sudoers_file)
        return
    
    print("  ✓ Configured deploy user sudoers")


def create_app_directories(config: SetupConfig) -> None:
    """Create directories for app deployments."""
    directories = [
        "/var/www",
        "/var/log/infra_tools/web",
        "/etc/nginx/sites-available",
        "/etc/nginx/sites-enabled",
    ]
    
    for directory in directories:
        os.makedirs(directory, mode=0o755, exist_ok=True)
    
    run("chown -R deploy:deploy /var/www", check=False)
    run("chmod -R 775 /var/www", check=False)
    
    print("  ✓ Created app directories")


def configure_deploy_ssh_access(config: SetupConfig) -> None:
    """Ensure SSH access is configured for deploy user."""
    ssh_dir = "/home/deploy/.ssh"
    auth_keys = f"{ssh_dir}/authorized_keys"
    
    if not os.path.exists(ssh_dir):
        os.makedirs(ssh_dir, mode=0o700)
        run(f"chown deploy:deploy {ssh_dir}")
    
    if not os.path.exists(auth_keys):
        run(f"touch {auth_keys}")
        run(f"chmod 600 {auth_keys}")
        run(f"chown deploy:deploy {auth_keys}")
    
    print("  ✓ Configured deploy SSH access")
    print(f"  ℹ Add build server public key to: {auth_keys}")


def configure_app_nginx(config: SetupConfig) -> None:
    """Configure nginx for app server."""
    if is_service_active("nginx"):
        print("  ✓ nginx already running")
        return
    
    run("systemctl enable nginx")
    run("systemctl start nginx")
    
    print("  ✓ nginx configured for app server")