"""SSL/TLS and Let's Encrypt certificate management."""

import os
import shlex
from typing import Optional, Callable, List

from .utils import run


def install_certbot(**kwargs) -> None:
    """Install certbot for Let's Encrypt certificate management."""
    os_type = kwargs.get('os_type', 'debian')
    
    print("Installing certbot...")
    if os_type in ['debian', 'ubuntu']:
        run("apt-get update")
        run("apt-get install -y certbot python3-certbot-nginx")
    else:
        print(f"  ⚠ Unsupported OS type for certbot installation: {os_type}")
        return
    
    print("  ✓ certbot installed")


def obtain_letsencrypt_certificate(domain: str, email: Optional[str] = None, run_func: Optional[Callable] = None) -> bool:
    """
    Obtain a Let's Encrypt certificate for a domain.
    
    Args:
        domain: Domain name to obtain certificate for
        email: Email address for Let's Encrypt registration (optional)
        run_func: Function to run commands (defaults to utils.run)
    
    Returns:
        True if successful, False otherwise
    """
    if run_func is None:
        run_func = run
    
    # Check if certificate already exists
    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    if os.path.exists(cert_path):
        print(f"  Certificate for {domain} already exists, skipping...")
        return True
    
    print(f"  Obtaining Let's Encrypt certificate for {domain}...")
    
    # Ensure the webroot exists
    run_func("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    # Build certbot command
    cmd_parts = [
        "certbot certonly",
        "--webroot",
        "-w /var/www/letsencrypt",
        f"-d {shlex.quote(domain)}",
        "--non-interactive",
        "--agree-tos",
    ]
    
    if email:
        cmd_parts.append(f"--email {shlex.quote(email)}")
    else:
        cmd_parts.append("--register-unsafely-without-email")
    
    cmd = " ".join(cmd_parts)
    
    result = run_func(cmd, check=False)
    
    if result.returncode == 0:
        print(f"  ✓ Certificate obtained for {domain}")
        return True
    else:
        print(f"  ⚠ Failed to obtain certificate for {domain}")
        return False


def setup_certificate_renewal(run_func: Optional[Callable] = None) -> None:
    """
    Set up automatic certificate renewal using certbot's built-in timer.
    
    Args:
        run_func: Function to run commands (defaults to utils.run)
    """
    if run_func is None:
        run_func = run
    
    print("  Setting up automatic certificate renewal...")
    
    # Enable and start certbot timer (systemd)
    run_func("systemctl enable certbot.timer", check=False)
    run_func("systemctl start certbot.timer", check=False)
    
    print("  ✓ Automatic renewal configured")


def update_nginx_to_use_letsencrypt(domain: str, run_func: Optional[Callable] = None) -> bool:
    """
    Update nginx configuration to use Let's Encrypt certificates.
    
    Args:
        domain: Domain name
        run_func: Function to run commands (defaults to utils.run)
    
    Returns:
        True if successful, False otherwise
    """
    if run_func is None:
        run_func = run
    
    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"
    
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print(f"  ⚠ Let's Encrypt certificates not found for {domain}")
        return False
    
    # Find nginx config file for this domain
    config_name = domain.replace('.', '_')
    config_file = f"/etc/nginx/sites-available/{config_name}"
    
    if not os.path.exists(config_file):
        print(f"  ⚠ Nginx config not found: {config_file}")
        return False
    
    print(f"  Updating nginx config to use Let's Encrypt certificates for {domain}...")
    
    # Read the config file
    try:
        with open(config_file, 'r') as f:
            content = f.read()
        
        # Replace self-signed certificate paths with Let's Encrypt paths
        old_cert = f"/etc/nginx/ssl/{domain}.crt"
        old_key = f"/etc/nginx/ssl/{domain}.key"
        
        content = content.replace(old_cert, cert_path)
        content = content.replace(old_key, key_path)
        
        # Write back
        with open(config_file, 'w') as f:
            f.write(content)
        
        print(f"  ✓ Updated nginx config for {domain}")
        
        # Test nginx configuration
        result = run_func("nginx -t", check=False)
        if result.returncode != 0:
            print("  ⚠ nginx configuration test failed")
            return False
        
        # Reload nginx
        run_func("systemctl reload nginx")
        print("  ✓ nginx reloaded")
        
        return True
    except Exception as e:
        print(f"  ⚠ Error updating nginx config: {e}")
        return False


def setup_ssl_for_deployments(deployments: List[dict], email: Optional[str] = None, run_func: Optional[Callable] = None) -> None:
    """
    Set up Let's Encrypt SSL certificates for deployed domains.
    
    Args:
        deployments: List of deployment info dictionaries with 'domain' keys
        email: Email address for Let's Encrypt registration
        run_func: Function to run commands (defaults to utils.run)
    """
    if run_func is None:
        run_func = run
    
    print("\n" + "=" * 60)
    print("Setting up Let's Encrypt SSL certificates...")
    print("=" * 60)
    
    # Get unique domains from deployments
    domains = set()
    for dep in deployments:
        domain = dep.get('domain')
        if domain:
            domains.add(domain)
            
            # Also check for API subdomains (for Rails apps at root path)
            if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                if not dep.get('path') or dep.get('path') == '/':
                    domains.add(f"api.{domain}")
    
    if not domains:
        print("  No domains to configure SSL for (only local path deployments)")
        return
    
    # Obtain certificates for all domains
    successful_domains = []
    for domain in sorted(domains):
        if obtain_letsencrypt_certificate(domain, email, run_func):
            successful_domains.append(domain)
    
    if not successful_domains:
        print("  ⚠ No certificates obtained")
        return
    
    # Update nginx configs to use the new certificates
    for domain in successful_domains:
        update_nginx_to_use_letsencrypt(domain, run_func)
    
    # Set up automatic renewal
    setup_certificate_renewal(run_func)
    
    print("  ✓ SSL setup complete")
