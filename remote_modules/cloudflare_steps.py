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

## Automated Setup

Run the automated setup script to configure your Cloudflare tunnel:

```bash
sudo setup-cloudflare-tunnel
```

This script will:
1. Install cloudflared (if not installed)
2. Guide you through Cloudflare authentication
3. Create a tunnel
4. Discover configured sites from nginx
5. Generate config.yml automatically
6. Install and start the tunnel service

## Manual Configuration

If you prefer manual setup or need to customize:

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

## State File

The automated setup script saves its state to `/etc/cloudflared/tunnel-state.json`.
This allows you to re-run the script to update the configuration when you add new sites.

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
    """Install Python script for comprehensive Cloudflare tunnel setup."""
    helper_script = "/usr/local/bin/setup-cloudflare-tunnel"
    
    if os.path.exists(helper_script):
        print("  ✓ Cloudflare tunnel setup script already exists")
        return
    
    # Read the Python script from the remote_modules directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_script = os.path.join(script_dir, "setup_cloudflare_tunnel.py")
    
    if not os.path.exists(source_script):
        print(f"  ⚠ Source script not found: {source_script}")
        return
    
    # Copy the script to /usr/local/bin
    with open(source_script, 'r') as src:
        script_content = src.read()
    
    with open(helper_script, 'w') as dst:
        dst.write(script_content)
    
    os.chmod(helper_script, 0o755)
    
    print(f"  ✓ Installed setup script: {helper_script}")
    print(f"  Run 'sudo setup-cloudflare-tunnel' to configure the tunnel")
