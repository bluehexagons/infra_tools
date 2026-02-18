#!/usr/bin/env python3
"""
Cloudflare Tunnel Setup Script

This script automates the complete setup of Cloudflare tunnels for deployed sites.
It can be run directly on the server after the initial --cloudflare preconfiguration.
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
import platform
import glob
import re
import shutil
from typing import Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.types import StrDict, JSONDict


CONFIG_DIR = "/etc/cloudflared"
STATE_FILE = "/etc/cloudflared/tunnel-state.json"
NGINX_SITES_DIR = "/etc/nginx/sites-enabled"


def run_command(cmd: list[str], check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command and optionally capture output."""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            print(f"✗ Command failed: {' '.join(cmd)}")
            if e.stderr:
                print(f"  Error: {e.stderr}")
            sys.exit(1)
        raise



def check_root():
    """Ensure script is run as root."""
    if os.geteuid() != 0:
        print("✗ This script must be run as root")
        print("  Please run: sudo python3 setup_cloudflare_tunnel.py")
        sys.exit(1)


def detect_architecture() -> str:
    """Detect system architecture and return appropriate package name."""
    arch = platform.machine()
    
    arch_map = {
        'x86_64': 'cloudflared-linux-amd64.deb',
        'aarch64': 'cloudflared-linux-arm64.deb',
        'arm64': 'cloudflared-linux-arm64.deb',
        'armv7l': 'cloudflared-linux-arm.deb',
    }
    
    package = arch_map.get(arch)
    if not package:
        print(f"✗ Unsupported architecture: {arch}")
        sys.exit(1)
    
    return package


def install_cloudflared():
    """Install cloudflared if not already installed."""
    if shutil.which('cloudflared'):
        print("✓ cloudflared already installed")
        return
    
    print("Installing cloudflared...")
    package = detect_architecture()
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{package}"
    
    print(f"  Downloading {package}...")
    run_command(['wget', '-q', url])
    
    print("  Installing package...")
    run_command(['dpkg', '-i', package])
    
    os.remove(package)
    print("✓ cloudflared installed successfully")


def authenticate_cloudflare():
    """Guide user through Cloudflare authentication."""
    print("\nAuthentication Required")
    print("=" * 50)
    print("You need to authenticate with Cloudflare.")
    print("This will open a browser window for login.")
    print()
    
    input("Press Enter to continue with authentication...")
    
    print("\nRunning: cloudflared tunnel login")
    result = run_command(['cloudflared', 'tunnel', 'login'], check=False)
    
    if result.returncode != 0:
        print("✗ Authentication failed")
        sys.exit(1)
    
    cert_file = '/root/.cloudflared/cert.pem'
    if not os.path.exists(cert_file):
        print(f"✗ Certificate file not found at {cert_file}")
        sys.exit(1)
    
    print("✓ Authentication successful")
    return cert_file


def create_tunnel(tunnel_name: str) -> dict[str, Any]:
    """Create a new Cloudflare tunnel."""
    print(f"\nCreating tunnel: {tunnel_name}")
    
    result = run_command(
        ['cloudflared', 'tunnel', 'create', tunnel_name],
        capture_output=True
    )
    
    output = result.stdout
    tunnel_id_match = re.search(r'Created tunnel .+ with id ([a-f0-9-]+)', output)
    
    if not tunnel_id_match:
        print("✗ Failed to extract tunnel ID from output")
        sys.exit(1)
    
    tunnel_id = tunnel_id_match.group(1)
    credentials_file = f'/root/.cloudflared/{tunnel_id}.json'
    
    if not os.path.exists(credentials_file):
        print(f"✗ Credentials file not found: {credentials_file}")
        sys.exit(1)
    
    dest_credentials = f"{CONFIG_DIR}/{tunnel_id}.json"
    
    os.makedirs(CONFIG_DIR, mode=0o755, exist_ok=True)
    
    with open(credentials_file, 'r') as src:
        credentials_data = json.load(src)
    
    with open(dest_credentials, 'w') as dst:
        json.dump(credentials_data, dst, indent=2)
    
    os.chmod(dest_credentials, 0o600)
    
    print(f"✓ Tunnel created: {tunnel_name} (ID: {tunnel_id})")
    
    return {
        'name': tunnel_name,
        'id': tunnel_id,
        'credentials_file': dest_credentials
    }


def discover_nginx_sites() -> list[StrDict]:
    """Discover sites from nginx configuration."""
    sites: list[StrDict] = []
    
    if not os.path.exists(NGINX_SITES_DIR):
        print(f"  ⚠ Nginx sites directory not found: {NGINX_SITES_DIR}")
        return sites
    
    for config_file in glob.glob(f"{NGINX_SITES_DIR}/*"):
        if os.path.islink(config_file):
            target = os.readlink(config_file)
            if not os.path.isabs(target):
                target = os.path.join(os.path.dirname(config_file), target)
        else:
            target = config_file
        
        if not os.path.exists(target):
            continue
        
        try:
            with open(target, 'r') as f:
                content = f.read()
            
            server_name_matches = re.findall(r'server_name\s+([^;]+);', content)
            
            for match in server_name_matches:
                domains = match.strip().split()
                for domain in domains:
                    if domain and domain != '_' and not domain.startswith('*'):
                        sites.append({
                            'hostname': domain,
                            'service': 'http://localhost:80'
                        })
        except Exception as e:
            print(f"  ⚠ Error reading {target}: {e}")
    
    return sites


def generate_config_yml(tunnel: JSONDict, sites: list[StrDict]) -> str:
    """Generate cloudflared config.yml content."""
    config_lines = [
        f"tunnel: {tunnel['id']}",
        f"credentials-file: {tunnel['credentials_file']}",
        "",
        "ingress:"
    ]
    
    for site in sites:
        config_lines.append(f"  - hostname: {site['hostname']}")
        config_lines.append(f"    service: {site['service']}")
    
    config_lines.append("  - service: http_status:404")
    config_lines.append("")
    
    return "\n".join(config_lines)


def save_state(tunnel: JSONDict, sites: list[StrDict]):
    """Save tunnel state for future runs."""
    state: JSONDict = {
        'tunnel': tunnel,
        'sites': sites
    }
    
    os.makedirs(CONFIG_DIR, mode=0o755, exist_ok=True)
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    os.chmod(STATE_FILE, 0o600)


def load_state() -> Optional[dict[str, Any]]:
    """Load saved tunnel state."""
    if not os.path.exists(STATE_FILE):
        return None
    
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠ Error loading state file: {e}")
        return None


def install_and_start_service(tunnel_name: str):
    """Install and start the cloudflared service."""
    print("\nInstalling cloudflared service...")
    
    run_command(['cloudflared', 'service', 'install'])
    
    print("✓ Service installed")
    
    print("\nStarting cloudflared service...")
    run_command(['systemctl', 'start', 'cloudflared'])
    run_command(['systemctl', 'enable', 'cloudflared'])
    
    print("✓ Service started and enabled")


def show_tunnel_info(tunnel: JSONDict, sites: list[StrDict]):
    """Display tunnel configuration information."""
    print("\n" + "=" * 50)
    print("Tunnel Configuration Summary")
    print("=" * 50)
    print(f"Tunnel Name: {tunnel['name']}")
    print(f"Tunnel ID: {tunnel['id']}")
    print(f"\nConfigured Sites ({len(sites)}):")
    for site in sites:
        print(f"  • {site['hostname']} -> {site['service']}")
    print()


def main(interactive: bool = True, auto_update: bool = False):
    """
    Main setup workflow.
    
    Args:
        interactive: If False, runs in non-interactive mode (auto-update only)
        auto_update: If True, automatically updates existing tunnel config
    """
    if interactive:
        print("=" * 50)
        print("Cloudflare Tunnel Setup")
        print("=" * 50)
        print()
    
    check_root()
    
    install_cloudflared()
    
    state = load_state()
    
    if not interactive:
        if not state:
            return False
        
        tunnel = state['tunnel']
        sites = discover_nginx_sites()
        
        if not sites:
            return False
        
        old_sites = state.get('sites', [])
        old_hostnames = set(s['hostname'] for s in old_sites)
        new_hostnames = set(s['hostname'] for s in sites)
        
        if old_hostnames == new_hostnames:
            return True
        
        config_content = generate_config_yml(tunnel, sites)
        config_file = f"{CONFIG_DIR}/config.yml"
        
        with open(config_file, 'w') as f:
            f.write(config_content)
        
        os.chmod(config_file, 0o600)
        
        save_state(tunnel, sites)
        
        result = run_command(['systemctl', 'is-active', 'cloudflared'], check=False, capture_output=True)
        if result.returncode == 0:
            run_command(['systemctl', 'restart', 'cloudflared'], check=False)
        
        return True
    
    # Interactive mode falls through to show configuration and return True on success
    if state:
        print("\n✓ Found existing tunnel configuration")
        tunnel = state['tunnel']
        
        print(f"  Tunnel: {tunnel['name']} (ID: {tunnel['id']})")
        
        if auto_update:
            choice = '1'
        else:
            print("\nOptions:")
            print("  1. Update tunnel configuration (discover new sites)")
            print("  2. Create a new tunnel")
            print("  3. Exit")
            
            while True:
                choice = input("\nEnter choice (1-3): ").strip().lower()
                
                if choice in ['3', 'exit', 'quit', 'q']:
                    print("Exiting...")
                    sys.exit(0)
                elif choice in ['2', 'new']:
                    state = None
                    break
                elif choice in ['1', 'update']:
                    break
                else:
                    print("✗ Invalid choice. Please enter 1, 2, or 3.")
        
        if choice in ['1', 'update']:
            pass  # Continue with tunnel from state
        else:
            state = None
    
    if not state:
        authenticate_cloudflare()
        
        while True:
            tunnel_name = input("\nEnter tunnel name (e.g., my-server): ").strip()
            
            if not tunnel_name:
                print("✗ Tunnel name cannot be empty")
                continue
            
            if not re.match(r'^[a-zA-Z0-9_-]+$', tunnel_name):
                print("✗ Tunnel name can only contain letters, numbers, hyphens, and underscores")
                continue
            
            if len(tunnel_name) > 64:
                print("✗ Tunnel name too long (max 64 characters)")
                continue
            
            break
        
        tunnel = create_tunnel(tunnel_name)
    else:
        tunnel = state['tunnel']
        print(f"\n✓ Using existing tunnel: {tunnel['name']}")
    
    print("\nDiscovering configured sites from nginx...")
    sites = discover_nginx_sites()
    
    if not sites:
        print("  ⚠ No sites discovered from nginx configuration")
        print("\nYou can manually add sites to the configuration.")
        
        manual = input("Add a site manually? (y/n): ").strip().lower()
        if manual == 'y':
            hostname = input("Enter hostname (e.g., example.com): ").strip()
            if hostname:
                sites.append({
                    'hostname': hostname,
                    'service': 'http://localhost:80'
                })
    
    if not sites:
        print("\n✗ No sites configured. Exiting.")
        sys.exit(1)
    
    print(f"\n✓ Found {len(sites)} site(s) to configure")
    
    config_content = generate_config_yml(tunnel, sites)
    config_file = f"{CONFIG_DIR}/config.yml"
    
    print(f"\nWriting configuration to {config_file}...")
    with open(config_file, 'w') as f:
        f.write(config_content)
    
    os.chmod(config_file, 0o600)
    print("✓ Configuration file created")
    
    save_state(tunnel, sites)
    
    show_tunnel_info(tunnel, sites)
    
    proceed = input("Install and start the tunnel service? (y/n): ").strip().lower()
    
    if proceed == 'y':
        install_and_start_service(tunnel['name'])
        
        print("\n" + "=" * 50)
        print("Setup Complete!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Go to Cloudflare Zero Trust dashboard")
        print("2. Configure DNS for your domains to point to the tunnel")
        print("3. Monitor tunnel status: systemctl status cloudflared")
        print()
    else:
        print("\n✓ Configuration saved")
        print(f"  Config file: {config_file}")
        print("\nTo start the tunnel later, run:")
        print("  cloudflared service install")
        print("  systemctl start cloudflared")
        print("  systemctl enable cloudflared")


def run_non_interactive_update() -> bool:
    """
    Run tunnel configuration update in non-interactive mode.
    Only updates existing tunnel configurations with newly discovered sites.
    Returns True if successful, False otherwise.
    """
    try:
        result = main(interactive=False)
        return bool(result)
    except Exception:
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cloudflare Tunnel Setup")
    parser.add_argument('--non-interactive', action='store_true',
                       help='Run in non-interactive mode (only updates existing tunnels)')
    parser.add_argument('--auto-update', action='store_true',
                       help='Automatically update existing tunnel without prompts')
    
    args = parser.parse_args()
    
    try:
        if args.non_interactive:
            success = main(interactive=False)
            sys.exit(0 if success else 1)
        else:
            main(interactive=True, auto_update=args.auto_update)
    except KeyboardInterrupt:
        print("\n\n✗ Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
