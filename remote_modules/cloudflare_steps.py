"""Cloudflare tunnel preconfiguration steps."""

import os

from .utils import run


def configure_cloudflare_firewall(os_type: str, **_) -> None:
    """Configure firewall for Cloudflare tunnel (SSH only, no HTTP/HTTPS)."""
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode == 0:
        result_80 = run("ufw status | grep -q '80/tcp'", check=False)
        result_443 = run("ufw status | grep -q '443/tcp'", check=False)
        if result_80.returncode != 0 and result_443.returncode != 0:
            print("  ✓ Firewall already configured for Cloudflare tunnel")
            return
    
    run("apt-get install -y -qq ufw")
    run("ufw default deny incoming")
    run("ufw default allow outgoing")
    run("ufw allow ssh")
    run("ufw --force enable")
    
    print("  ✓ Firewall configured for Cloudflare tunnel (SSH only)")


def create_cloudflared_config_directory(**_) -> None:
    """Create cloudflared configuration directory structure."""
    config_dir = "/etc/cloudflared"
    
    if os.path.exists(config_dir):
        print(f"  ✓ Cloudflared config directory already exists")
        return
    
    os.makedirs(config_dir, mode=0o755, exist_ok=True)
    
    readme_content = """# Cloudflare Tunnel Configuration

This directory is preconfigured for cloudflared setup.

## Installation Steps

1. Install cloudflared:
   ```
   wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   ```

2. Authenticate with Cloudflare:
   ```
   cloudflared tunnel login
   ```

3. Create a tunnel:
   ```
   cloudflared tunnel create <tunnel-name>
   ```

4. Create config.yml in this directory with your tunnel configuration.

5. Install and start the tunnel service:
   ```
   cloudflared service install
   systemctl start cloudflared
   systemctl enable cloudflared
   ```

## Configuration Template

The config.yml should look like:

```yaml
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json

ingress:
  - hostname: example.com
    service: http://localhost:80
  - hostname: api.example.com
    service: http://localhost:80
  - service: http_status:404
```

For more information: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
"""
    
    with open(os.path.join(config_dir, "README.md"), "w") as f:
        f.write(readme_content)
    
    print(f"  ✓ Created {config_dir} with setup instructions")


def configure_nginx_for_cloudflare(**_) -> None:
    """Configure nginx to trust Cloudflare IPs and use real visitor IPs."""
    cloudflare_conf = "/etc/nginx/conf.d/cloudflare.conf"
    
    if os.path.exists(cloudflare_conf):
        print("  ✓ Nginx already configured for Cloudflare")
        return
    
    # Cloudflare IPv4 and IPv6 ranges
    # Note: These ranges may change. Verify current ranges at:
    # https://www.cloudflare.com/ips/
    cloudflare_config = """# Cloudflare IP ranges for real IP restoration
# Verify current ranges at: https://www.cloudflare.com/ips/
# Last updated: 2024-12

# IPv4
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;

# IPv6
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;

# Use CF-Connecting-IP header to get real visitor IP
real_ip_header CF-Connecting-IP;
"""
    
    os.makedirs("/etc/nginx/conf.d", exist_ok=True)
    
    with open(cloudflare_conf, "w") as f:
        f.write(cloudflare_config)
    
    print("  ✓ Nginx configured to trust Cloudflare IPs")


def install_cloudflared_service_helper(**_) -> None:
    """Create helper script for cloudflared installation."""
    helper_script = "/usr/local/bin/setup-cloudflare-tunnel"
    
    if os.path.exists(helper_script):
        print("  ✓ Cloudflare tunnel helper script already exists")
        return
    
    script_content = """#!/bin/bash
# Helper script for setting up Cloudflare tunnel

set -e

echo "Cloudflare Tunnel Setup Helper"
echo "==============================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (use sudo)"
    exit 1
fi

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        PACKAGE="cloudflared-linux-amd64.deb"
        ;;
    aarch64|arm64)
        PACKAGE="cloudflared-linux-arm64.deb"
        ;;
    armv7l)
        PACKAGE="cloudflared-linux-arm.deb"
        ;;
    *)
        echo "Error: Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

# Install cloudflared if not already installed
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared for $ARCH..."
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/$PACKAGE
    dpkg -i $PACKAGE
    rm $PACKAGE
    echo "✓ cloudflared installed"
else
    echo "✓ cloudflared already installed"
fi

echo ""
echo "Next steps:"
echo "1. Authenticate: cloudflared tunnel login"
echo "2. Create tunnel: cloudflared tunnel create <name>"
echo "3. Create /etc/cloudflared/config.yml (see /etc/cloudflared/README.md)"
echo "4. Install service: cloudflared service install"
echo "5. Start service: systemctl start cloudflared && systemctl enable cloudflared"
echo ""
echo "Configuration directory: /etc/cloudflared/"
"""
    
    with open(helper_script, "w") as f:
        f.write(script_content)
    
    os.chmod(helper_script, 0o755)
    
    print(f"  ✓ Created helper script: {helper_script}")
