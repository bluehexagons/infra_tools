"""CI/CD webhook system setup steps."""

from __future__ import annotations

import os
import secrets
import json

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed
from lib.systemd_service import cleanup_service


def install_cicd_dependencies(config: SetupConfig) -> None:
    """Install dependencies required for CI/CD system."""
    packages = ['git']
    
    missing_packages = [pkg for pkg in packages if not is_package_installed(pkg)]
    
    if not missing_packages:
        print("  ✓ CI/CD dependencies already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(f"apt-get install -y -qq {' '.join(missing_packages)}")
    
    print("  ✓ CI/CD dependencies installed")


def create_cicd_user(config: SetupConfig) -> None:
    """Create dedicated user for webhook receiver service."""
    user = "webhook"
    
    result = run(f"id {user}", check=False)
    if result.returncode == 0:
        print(f"  ✓ User '{user}' already exists")
        return
    
    run(f"useradd --system --no-create-home --shell /usr/sbin/nologin {user}")
    print(f"  ✓ Created user '{user}'")


def create_cicd_directories(config: SetupConfig) -> None:
    """Create directories for CI/CD system."""
    directories = [
        "/etc/infra_tools/cicd",
        "/var/lib/infra_tools/cicd/jobs",
        "/var/lib/infra_tools/cicd/workspaces",
        "/var/lib/infra_tools/cicd/logs",
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory, mode=0o755, exist_ok=True)
    
    # Set ownership
    run("chown -R webhook:webhook /var/lib/infra_tools/cicd", check=False)
    run("chmod -R 750 /var/lib/infra_tools/cicd", check=False)
    
    print("  ✓ Created CI/CD directories")


def generate_webhook_secret(config: SetupConfig) -> str:
    """Generate a secure webhook secret and store it."""
    secret_file = "/etc/infra_tools/cicd/webhook_secret"
    
    if os.path.exists(secret_file):
        with open(secret_file, 'r') as f:
            secret = f.read().strip()
        print("  ✓ Using existing webhook secret")
        return secret
    
    # Generate a secure random secret
    secret = secrets.token_urlsafe(32)
    
    # Save secret to file with restricted permissions
    with open(secret_file, 'w') as f:
        f.write(secret)
    
    os.chmod(secret_file, 0o600)
    run("chown root:root /etc/infra_tools/cicd/webhook_secret", check=False)
    
    print("  ✓ Generated webhook secret")
    print(f"  ℹ Secret stored in: {secret_file}")
    
    return secret


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
    
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    os.chmod(config_file, 0o644)
    
    print("  ✓ Created default webhook configuration")
    print(f"  ℹ Edit configuration: {config_file}")


def create_webhook_receiver_service(config: SetupConfig) -> None:
    """Create systemd service for webhook receiver."""
    service_name = "webhook-receiver"
    
    # Cleanup existing service
    cleanup_service(service_name)
    
    # Get webhook secret
    secret_file = "/etc/infra_tools/cicd/webhook_secret"
    if not os.path.exists(secret_file):
        print("  ⚠ Webhook secret not found, generating...")
        generate_webhook_secret(config)
    
    # Read secret
    with open(secret_file, 'r') as f:
        secret = f.read().strip()
    
    # Create service unit file
    service_content = f"""[Unit]
Description=Webhook Receiver for CI/CD
After=network.target

[Service]
Type=simple
User=webhook
Group=webhook
WorkingDirectory=/opt/infra_tools/web/service_tools
Environment="WEBHOOK_SECRET={secret}"
Environment="WEBHOOK_PORT=8765"
ExecStart=/usr/bin/python3 /opt/infra_tools/web/service_tools/webhook_receiver.py
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/infra_tools/cicd

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
    """Create systemd service for CI/CD executor."""
    service_name = "cicd-executor"
    
    # Cleanup existing service
    cleanup_service(service_name)
    
    # Create service unit file (one-shot service triggered by webhook receiver)
    service_content = """[Unit]
Description=CI/CD Job Executor
After=network.target

[Service]
Type=oneshot
User=webhook
Group=webhook
WorkingDirectory=/opt/infra_tools/web/service_tools
ExecStart=/usr/bin/python3 /opt/infra_tools/web/service_tools/cicd_executor.py

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/infra_tools/cicd

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cicd-executor
"""
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    run("systemctl daemon-reload")
    
    print(f"  ✓ Created {service_name}.service")


def configure_nginx_for_webhook(config: SetupConfig) -> None:
    """Configure nginx to reverse proxy webhook endpoint."""
    nginx_conf = "/etc/nginx/conf.d/webhook.conf"
    
    if os.path.exists(nginx_conf):
        print("  ✓ Nginx webhook configuration already exists")
        return
    
    # Create nginx configuration with rate limiting
    nginx_content = """# Webhook receiver reverse proxy
# Rate limiting zone: 10 requests per minute per IP
limit_req_zone $binary_remote_addr zone=webhook_limit:10m rate=10r/m;

server {
    listen 127.0.0.1:8080;
    server_name _;
    
    location /webhook {
        # Rate limiting
        limit_req zone=webhook_limit burst=5 nodelay;
        limit_req_status 429;
        
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
