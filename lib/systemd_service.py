"""Systemd service creation for deployed applications."""

import os
import shlex
import secrets
import re
import sys
from typing import Optional

# Add parent directory to path to import from remote_modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.remote_utils import run


def generate_node_service(app_name: str, app_path: str, port: int = 4000,
                         web_user: str = "www-data", web_group: str = "www-data",
                         build_dir: str = "dist") -> str:
    """Generate systemd service configuration for a Node.js application."""
    return f"""[Unit]
Description=Node app: {app_name}
After=network.target

[Service]
Type=simple
User={web_user}
Group={web_group}
WorkingDirectory={app_path}
Environment="NODE_ENV=production"
Environment="PORT={port}"
ExecStart=/usr/local/bin/npx -y serve -s {build_dir} -l {port}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def create_node_service(app_name: str, app_path: str, port: int,
                       web_user: str, web_group: str) -> None:
    """Create and enable a Node.js systemd service."""
    service_name = f"node-{app_name}"
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    if os.path.exists(service_file):
        print(f"  ℹ Service {service_name} already exists, updating...")
    
    # Detect build directory
    build_dir = "dist"
    if os.path.exists(os.path.join(app_path, "build")):
        build_dir = "build"
    elif os.path.exists(os.path.join(app_path, "out")):
        build_dir = "out"
    
    service_content = generate_node_service(app_name, app_path, port, web_user, web_group, build_dir)
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write service file {service_file}. Need root permissions.") from e
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}")
    run(f"systemctl restart {service_name}")
    
    print(f"  ✓ Created and started systemd service: {service_name}")
    
    # Give service a moment to start
    import time
    time.sleep(1)
    
    # Check if service is running
    result = run(f"systemctl is-active {service_name}", check=False)
    if result.returncode != 0:
        print(f"  ⚠ Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
    else:
        print(f"  ✓ {service_name} is running")


def generate_rails_service(app_name: str, app_path: str, secret_key_base: str, port: int = 3000,
                          web_user: str = "www-data", web_group: str = "www-data",
                          extra_env: Optional[dict] = None) -> str:
    """Generate systemd service configuration for a Rails application."""
    env_lines = [
        'Environment="RAILS_ENV=production"',
        'Environment="RAILS_LOG_TO_STDOUT=true"',
        'Environment="RAILS_SERVE_STATIC_FILES=true"',
        f'Environment="SECRET_KEY_BASE={secret_key_base}"'
    ]
    
    if extra_env:
        for key, value in extra_env.items():
            env_lines.append(f'Environment="{key}={value}"')
            
    env_section = "\n".join(env_lines)
    
    return f"""[Unit]
Description=Rails app: {app_name}
After=network.target

[Service]
Type=simple
User={web_user}
Group={web_group}
WorkingDirectory={app_path}
{env_section}
ExecStart=/bin/bash -c 'exec bundle exec rails server -b 127.0.0.1 -p {port}'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def create_rails_service(app_name: str, app_path: str, port: int,
                        web_user: str, web_group: str,
                        env_vars: Optional[dict] = None) -> None:
    """Create and enable a Rails systemd service."""
    service_name = f"rails-{app_name}"
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    secret_key_base = secrets.token_hex(64)
    
    if os.path.exists(service_file):
        print(f"  ℹ Service {service_name} already exists, updating...")
        try:
            with open(service_file, 'r') as f:
                content = f.read()
                match = re.search(r'Environment="SECRET_KEY_BASE=([a-f0-9]+)"', content)
                if match:
                    secret_key_base = match.group(1)
                    print(f"  ℹ Preserving existing SECRET_KEY_BASE")
        except Exception:
            pass
    
    service_content = generate_rails_service(app_name, app_path, secret_key_base, port, web_user, web_group, env_vars)
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write service file {service_file}. Need root permissions.") from e
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}")
    run(f"systemctl restart {service_name}")
    
    print(f"  ✓ Created and started systemd service: {service_name}")
    
    # Give service a moment to start
    import time
    time.sleep(1)
    
    # Check if service is running
    result = run(f"systemctl is-active {service_name}", check=False)
    if result.returncode != 0:
        print(f"  ⚠ Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
    else:
        print(f"  ✓ {service_name} is running")
