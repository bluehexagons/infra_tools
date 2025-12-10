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


def obtain_letsencrypt_certificate(domains: List[str], email: Optional[str] = None, run_func: Optional[Callable] = None, cert_name: Optional[str] = None) -> bool:
    """
    Obtain a Let's Encrypt certificate for one or more domains using SANs.
    
    Let's Encrypt allows up to 100 Subject Alternative Names per certificate,
    so we can request a single certificate covering multiple domains.
    
    Args:
        domains: List of domain names to include in the certificate
        email: Email address for Let's Encrypt registration (optional)
        run_func: Function to run commands (defaults to utils.run)
        cert_name: Name for the certificate (defaults to first domain)
    
    Returns:
        True if successful, False otherwise
    """
    if run_func is None:
        run_func = run
    
    if not domains:
        return False
    
    # Use first domain as cert name if not specified
    if cert_name is None:
        cert_name = domains[0]
    
    # Check if certificate already exists
    cert_path = f"/etc/letsencrypt/live/{cert_name}/fullchain.pem"
    if os.path.exists(cert_path):
        print(f"  Certificate '{cert_name}' already exists, skipping...")
        return True
    
    print(f"  Obtaining Let's Encrypt certificate for {len(domains)} domain(s): {', '.join(domains)}")
    
    # Ensure the webroot exists
    run_func("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    # Build certbot command with multiple domains
    cmd_parts = [
        "certbot certonly",
        "--webroot",
        "-w /var/www/letsencrypt",
        "--non-interactive",
        "--agree-tos",
    ]
    
    # Add certificate name
    cmd_parts.append(f"--cert-name {shlex.quote(cert_name)}")
    
    # Add all domains as SANs
    for domain in domains:
        cmd_parts.append(f"-d {shlex.quote(domain)}")
    
    if email:
        cmd_parts.append(f"--email {shlex.quote(email)}")
    else:
        cmd_parts.append("--register-unsafely-without-email")
    
    cmd = " ".join(cmd_parts)
    
    result = run_func(cmd, check=False)
    
    if result.returncode == 0:
        print(f"  ✓ Certificate '{cert_name}' obtained")
        return True
    else:
        print(f"  ⚠ Failed to obtain certificate '{cert_name}'")
        return False


def create_domain_cert_links(domains: List[str], cert_name: str, run_func: Optional[Callable] = None) -> None:
    """
    Create symbolic links for each domain pointing to the shared certificate.
    
    This makes it easier to determine if a domain has SSL configured by checking
    if /etc/letsencrypt/live/{domain} exists.
    
    Args:
        domains: List of domain names that share the certificate
        cert_name: Name of the certificate directory
        run_func: Function to run commands (defaults to utils.run)
    """
    if run_func is None:
        run_func = run
    
    cert_dir = f"/etc/letsencrypt/live/{cert_name}"
    
    if not os.path.exists(cert_dir):
        print(f"  ⚠ Certificate directory {cert_dir} not found")
        return
    
    for domain in domains:
        if domain == cert_name:
            # Skip the primary domain (it's the actual directory)
            continue
        
        link_path = f"/etc/letsencrypt/live/{domain}"
        
        # Check if link already exists
        if os.path.exists(link_path):
            # Check if it's already a correct link
            if os.path.islink(link_path):
                target = os.readlink(link_path)
                if target == cert_name or target == cert_dir:
                    continue
            else:
                print(f"  ⚠ {link_path} exists but is not a symlink, skipping")
                continue
        
        # Create symlink
        try:
            os.symlink(cert_name, link_path)
            print(f"  ✓ Created symlink: {domain} -> {cert_name}")
        except Exception as e:
            print(f"  ⚠ Failed to create symlink for {domain}: {e}")


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
    
    Uses Subject Alternative Names (SANs) to request a single certificate for all domains,
    reducing the number of certificates and making management easier.
    
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
    
    # Convert to sorted list for consistent ordering
    domain_list = sorted(domains)
    
    print(f"  Requesting certificate for {len(domain_list)} domain(s) using Subject Alternative Names")
    
    # Use the first domain alphabetically as the cert name
    cert_name = domain_list[0]
    
    # Request single certificate with all domains as SANs
    # Let's Encrypt allows up to 100 SANs per certificate
    if len(domain_list) > 100:
        print(f"  ⚠ Warning: {len(domain_list)} domains exceeds Let's Encrypt limit of 100 SANs")
        print(f"  ⚠ Only the first 100 domains will be included in the certificate")
        domain_list = domain_list[:100]
    
    success = obtain_letsencrypt_certificate(domain_list, email, run_func, cert_name)
    
    if not success:
        print("  ⚠ Failed to obtain certificate")
        return
    
    # Create symbolic links for each domain pointing to the shared certificate
    # This makes it easy to check if a domain has SSL by looking for /etc/letsencrypt/live/{domain}
    print(f"  Creating symbolic links for domain certificate references...")
    create_domain_cert_links(domain_list, cert_name, run_func)
    
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
    print(f"  ✓ Single certificate covers all {len(domain_list)} domain(s)")
