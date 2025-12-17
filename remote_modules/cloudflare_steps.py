"""Cloudflare tunnel preconfiguration steps."""

import os

from .utils import run


def configure_cloudflare_firewall(**_) -> None:
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
    
    # Explicitly remove web ports if they were added by previous steps
    run("ufw delete allow 80/tcp", check=False)
    run("ufw delete allow 443/tcp", check=False)
    run("ufw delete allow 80", check=False)
    run("ufw delete allow 443", check=False)
    
    run("ufw --force enable")
    
    print("  ✓ Firewall configured for Cloudflare tunnel (SSH only)")


def create_cloudflared_config_directory(**_) -> None:
    """Create cloudflared configuration directory structure."""
    config_dir = "/etc/cloudflared"
    
    if os.path.exists(config_dir):
        print(f"  ✓ Cloudflared config directory already exists")
        return
    
    os.makedirs(config_dir, mode=0o755, exist_ok=True)
    
    # Load README from template file
    template_path = os.path.join(os.path.dirname(__file__), 'cloudflare_tunnel_readme.md')
    with open(template_path, 'r', encoding='utf-8') as f:
        readme_content = f.read()
    
    with open(os.path.join(config_dir, "README.md"), "w") as f:
        f.write(readme_content)
    
    print(f"  ✓ Created {config_dir} with setup instructions")


def configure_nginx_for_cloudflare(**_) -> None:
    """Configure nginx to trust Cloudflare IPs and use real visitor IPs."""
    cloudflare_conf = "/etc/nginx/conf.d/cloudflare.conf"
    
    if os.path.exists(cloudflare_conf):
        print("  ✓ Nginx already configured for Cloudflare")
        return
    
    # Load Cloudflare configuration from template file
    template_path = os.path.join(os.path.dirname(__file__), 'cloudflare_ips.conf')
    with open(template_path, 'r', encoding='utf-8') as f:
        cloudflare_config = f.read()
    
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


def run_cloudflare_tunnel_setup(**_) -> None:
    """Run Cloudflare tunnel setup in non-interactive mode to update configuration."""
    helper_script = "/usr/local/bin/setup-cloudflare-tunnel"
    
    if not os.path.exists(helper_script):
        print("  ⚠ Cloudflare tunnel setup script not found")
        return
    
    # Check if there's an existing tunnel configuration
    state_file = "/etc/cloudflared/tunnel-state.json"
    if not os.path.exists(state_file):
        print("  ⚠ No existing Cloudflare tunnel found")
        print("  Run 'sudo setup-cloudflare-tunnel' interactively to create a tunnel first")
        return
    
    print("  Updating Cloudflare tunnel configuration...")
    
    # Run the setup script in non-interactive mode
    result = run(f"python3 {helper_script} --non-interactive", check=False)
    
    if result.returncode == 0:
        print("  ✓ Cloudflare tunnel configuration updated")
    else:
        print("  ⚠ Cloudflare tunnel update skipped (no changes or not configured)")
