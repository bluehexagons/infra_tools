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
    
    # Regenerate nginx configs to use the new Let's Encrypt certificates
    # Since nginx_config.py's get_ssl_cert_path() now prefers Let's Encrypt certs,
    # we just need to regenerate the configs
    print("\n  Regenerating nginx configurations to use Let's Encrypt certificates...")
    
    from collections import defaultdict
    from shared.nginx_config import create_nginx_sites_for_groups
    
    grouped_deployments = defaultdict(list)
    for dep in deployments:
        grouped_deployments[dep['domain']].append(dep)
    
    create_nginx_sites_for_groups(grouped_deployments, run_func)
    
    # Set up automatic renewal
    setup_certificate_renewal(run_func)
    
    print("  ✓ SSL setup complete")
