"""CI/CD webhook system setup steps."""

from __future__ import annotations

import os
import secrets

from lib.atomic_io import write_json_atomic, write_text_atomic
from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed
from lib.systemd_service import cleanup_service


CICD_USER = "webhook"
CICD_HOME = "/var/lib/infra_tools/cicd"


def install_cicd_dependencies(config: SetupConfig) -> None:
    """Install dependencies required for CI/CD system."""
    packages = ['git']
    
    def all_installed() -> bool:
        return all(is_package_installed(pkg) for pkg in packages)
    
    if all_installed():
        print("  ✓ CI/CD dependencies already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(f"apt-get install -y -qq {' '.join(packages)}", check=True)
    
    if all_installed():
        print("  ✓ CI/CD dependencies installed")
        return
    raise RuntimeError("CI/CD dependencies were not present after installation")


def create_cicd_user(config: SetupConfig) -> None:
    """Create dedicated user for webhook receiver service."""
    user = CICD_USER
    
    result = run(f"id {user}", check=False)
    if result.returncode == 0:
        run(f"usermod --home {CICD_HOME} {user}", check=True)
        print(f"  ✓ User '{user}' already exists")
        return
    
    run(f"useradd --system --home-dir {CICD_HOME} --no-create-home --shell /usr/sbin/nologin {user}")
    print(f"  ✓ Created user '{user}'")


def create_cicd_directories(config: SetupConfig) -> None:
    """Create directories for CI/CD system."""
    directories = [
        "/etc/infra_tools/cicd",
        f"{CICD_HOME}/jobs",
        f"{CICD_HOME}/workspaces",
        f"{CICD_HOME}/logs",
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory, mode=0o755, exist_ok=True)
    
    # Set ownership - critical for security
    # Ensure the 'webhook' user exists before attempting chown
    user_check = run(f"id {CICD_USER}", check=False)
    if user_check.returncode != 0:
        raise RuntimeError(
            f"Cannot secure CI/CD directories because user '{CICD_USER}' does not exist"
        )
    run(f"chown -R {CICD_USER}:{CICD_USER} {CICD_HOME}", check=True)
    run(f"chmod -R 750 {CICD_HOME}", check=True)
    
    print("  ✓ Created CI/CD directories")


def generate_webhook_secret(config: SetupConfig) -> str:
    """Generate a secure webhook secret and store it in an environment file."""
    secret_file = "/etc/infra_tools/cicd/webhook_secret"
    env_file = "/etc/infra_tools/cicd/webhook.env"
    
    if os.path.exists(secret_file):
        with open(secret_file, 'r') as f:
            secret = f.read().strip()
        
        if os.path.exists(env_file):
            print("  ✓ Using existing webhook secret")
            return secret
        
        _create_env_file(env_file, secret)
        print("  ✓ Created environment file for webhook secret")
        return secret
    
    secret = secrets.token_urlsafe(32)
    
    write_text_atomic(secret_file, secret, mode=0o600)
    run("chown root:root /etc/infra_tools/cicd/webhook_secret")
    
    _create_env_file(env_file, secret)
    
    print("  ✓ Generated webhook secret")
    print(f"  ℹ Secret stored in: {secret_file}")
    
    return secret


def _create_env_file(env_file: str, secret: str) -> None:
    """Create environment file for systemd service with restricted permissions."""
    write_text_atomic(
        env_file,
        f"WEBHOOK_SECRET={secret}\nWEBHOOK_PORT=8765\n",
        mode=0o600,
    )
    run(f"chown root:root {env_file}")


def create_default_webhook_config(config: SetupConfig) -> None:
    """Create default webhook configuration file."""
    config_file = "/etc/infra_tools/cicd/webhook_config.json"
    
    if os.path.exists(config_file):
        print("  ✓ Webhook configuration already exists")
        return
    
    # Create default configuration
    default_config = {
        "repositories": [
            {
                "url": "https://github.com/example/repo.git",
                "branches": ["main", "master"],
                "scripts": {
                    "install": "scripts/install.sh",
                    "build": "scripts/build.sh",
                    "test": "scripts/test.sh",
                    "deploy": "scripts/deploy.sh"
                }
            }
        ]
    }
    
    write_json_atomic(config_file, default_config, mode=0o644)
    
    print("  ✓ Created default webhook configuration")
    print(f"  ℹ Edit configuration: {config_file}")


def create_webhook_receiver_service(config: SetupConfig) -> None:
    """Create systemd service for webhook receiver."""
    service_name = "webhook-receiver"
    
    cleanup_service(service_name)
    
    secret_file = "/etc/infra_tools/cicd/webhook_secret"
    env_file = "/etc/infra_tools/cicd/webhook.env"
    if not os.path.exists(secret_file):
        print("  ⚠ Webhook secret not found, generating...")
        generate_webhook_secret(config)
    
    if not os.path.exists(env_file):
        print("  ⚠ Environment file not found, creating...")
        with open(secret_file, 'r') as f:
            secret = f.read().strip()
        _create_env_file(env_file, secret)
    
    service_content = """[Unit]
Description=Webhook Receiver for CI/CD
After=network.target

[Service]
Type=simple
User=webhook
Group=webhook
WorkingDirectory=/opt/infra_tools/web/service_tools
Environment=HOME=/var/lib/infra_tools/cicd
Environment=INFRA_TOOLS_WORKSPACE=/var/lib/infra_tools/cicd
EnvironmentFile=/etc/infra_tools/cicd/webhook.env
ExecStart=/usr/bin/python3 /opt/infra_tools/web/service_tools/webhook_receiver.py
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources @mount
ReadWritePaths=/var/lib/infra_tools/cicd/jobs
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0077

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=webhook-receiver

[Install]
WantedBy=multi-user.target
"""
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}.service")
    run(f"systemctl start {service_name}.service")
    
    print(f"  ✓ Created and started {service_name}.service")


def create_cicd_executor_service(config: SetupConfig) -> None:
    """Create systemd service + path unit for CI/CD executor.
    
    The executor is triggered by a systemd path unit that watches the jobs
    directory for new files written by the unprivileged webhook receiver.
    This avoids requiring the webhook user to have systemctl/polkit privileges
    to start the executor service (which previously made jobs silently fail
    to run when the webhook user could not invoke ``systemctl start``).
    """
    service_name = "cicd-executor"
    
    # Cleanup existing service (also removes any prior .path unit)
    cleanup_service(service_name)
    
    service_content = """[Unit]
Description=CI/CD Job Executor
After=network.target

[Service]
Type=oneshot
User=webhook
Group=webhook
WorkingDirectory=/opt/infra_tools/web/service_tools
Environment=HOME=/var/lib/infra_tools/cicd
Environment=INFRA_TOOLS_WORKSPACE=/var/lib/infra_tools/cicd
ExecStart=/usr/bin/python3 /opt/infra_tools/web/service_tools/cicd_executor.py
TimeoutStartSec=2h

# Security hardening (executor must run user-supplied scripts so we cannot
# apply MemoryDenyWriteExecute or SystemCallFilter without breaking common
# CI tooling such as Node and other JIT-compiled languages)
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
SystemCallArchitectures=native
ReadWritePaths=/var/lib/infra_tools/cicd /var/log/infra_tools
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cicd-executor
"""
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    # Path activator: triggers the executor whenever a job file is written by
    # the webhook receiver. The receiver runs as an unprivileged user that
    # cannot call ``systemctl start`` directly, so this is required.
    path_content = """[Unit]
Description=Watch CI/CD jobs directory for new jobs
After=network.target

[Path]
DirectoryNotEmpty=/var/lib/infra_tools/cicd/jobs
PathChanged=/var/lib/infra_tools/cicd/jobs
Unit=cicd-executor.service

[Install]
WantedBy=multi-user.target
"""
    
    path_file = f"/etc/systemd/system/{service_name}.path"
    with open(path_file, 'w') as f:
        f.write(path_content)
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}.path")
    run(f"systemctl start {service_name}.path")
    
    print(f"  ✓ Created {service_name}.service and {service_name}.path")


def configure_nginx_for_webhook(config: SetupConfig) -> None:
    """Configure nginx to reverse proxy webhook endpoint."""
    nginx_conf = "/etc/nginx/conf.d/webhook.conf"
    
    if os.path.exists(nginx_conf):
        print("  ✓ Nginx webhook configuration already exists")
        return
    
    # Create nginx configuration with rate limiting
    nginx_content = """# Webhook receiver reverse proxy
# Rate limiting zone: default 10 requests per minute per IP.
# NOTE: This conservative default may be too restrictive for repositories with
# frequent commits or for instances handling multiple repositories. If you see
# HTTP 429 responses from the webhook endpoint under normal load, consider
# increasing the `rate` (and optionally `burst`) values below to better match
# your expected webhook traffic pattern.
limit_req_zone $binary_remote_addr zone=webhook_limit:10m rate=10r/m;

server {
    listen 127.0.0.1:8080;
    server_name _;
    
    location /webhook {
        # Rate limiting
        limit_req zone=webhook_limit burst=5 nodelay;
        limit_req_status 429;
        client_max_body_size 1m;
        
        # Proxy to webhook receiver
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Pass through GitHub webhook headers
        proxy_set_header X-Hub-Signature-256 $http_x_hub_signature_256;
        proxy_set_header X-GitHub-Event $http_x_github_event;
        proxy_set_header X-GitHub-Delivery $http_x_github_delivery;
        
        # Timeouts
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
        
        # No buffering for webhook responses
        proxy_buffering off;
    }
    
    location /webhook/health {
        proxy_pass http://127.0.0.1:8765/health;
        access_log off;
    }
}
"""
    
    os.makedirs("/etc/nginx/conf.d", exist_ok=True)
    
    with open(nginx_conf, 'w') as f:
        f.write(nginx_content)
    
    # Test nginx configuration
    result = run("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed")
        os.remove(nginx_conf)
        return
    
    # Reload nginx
    run("systemctl reload nginx")
    
    print("  ✓ Configured nginx for webhook endpoint")


def update_cloudflare_tunnel_for_webhook(config: SetupConfig) -> None:
    """Update Cloudflare tunnel configuration to include webhook endpoint."""
    cloudflared_config = "/etc/cloudflared/config.yml"
    
    if not os.path.exists(cloudflared_config):
        print("  ℹ Cloudflare tunnel not configured, skipping")
        return
    
    # Read existing configuration
    with open(cloudflared_config, 'r') as f:
        content = f.read()
    
    # Check if webhook ingress already exists
    if 'service: http://localhost:8080' in content:
        print("  ✓ Cloudflare tunnel already configured for webhook")
        return
    
    print("  ℹ Cloudflare tunnel configuration needs manual update")
    print("  Add the following to your tunnel ingress rules:")
    print("    - hostname: webhook.yourdomain.com")
    print("      service: http://localhost:8080")


def install_webhook_manager_helper(config: SetupConfig) -> None:
    """Create symlink for webhook manager helper script."""
    helper_script = "/usr/local/bin/webhook-manager"
    source_script = "/opt/infra_tools/web/service_tools/webhook_manager.py"
    
    if os.path.exists(helper_script):
        print("  ✓ Webhook manager helper already available")
        return
    
    if not os.path.exists(source_script):
        print(f"  ⚠ Source script not found: {source_script}")
        return
    
    run(f"ln -sf {source_script} {helper_script}")
    run(f"chmod +x {source_script}")
    
    print(f"  ✓ Installed webhook manager: {helper_script}")
    print(f"  Run 'sudo webhook-manager list' to manage configurations")
