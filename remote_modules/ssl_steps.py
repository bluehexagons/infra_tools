"""SSL/TLS and Let's Encrypt certificate management."""

import os
import shlex
from typing import Optional, Callable, List

from lib.config import SetupConfig
from .utils import run


def install_certbot(config: SetupConfig) -> None:
    print("Installing certbot...")
    run("apt-get update")
    run("apt-get install -y certbot python3-certbot-nginx")
    print("  ✓ certbot installed")


def obtain_letsencrypt_certificate(domains: List[str], email: Optional[str] = None, cert_name: Optional[str] = None) -> bool:
    """
    Obtain a Let's Encrypt certificate for multiple domains using SANs.
    Let's Encrypt allows up to 100 Subject Alternative Names per certificate.
    """
    if not domains:
        return False
    
    if cert_name is None:
        cert_name = domains[0]
    
    cert_path = f"/etc/letsencrypt/live/{cert_name}/fullchain.pem"
    if os.path.exists(cert_path):
        print(f"  Certificate '{cert_name}' already exists, skipping...")
        return True
    
    print(f"  Obtaining Let's Encrypt certificate for {len(domains)} domain(s): {', '.join(domains)}")
    
    run("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    cmd_parts = [
        "certbot certonly",
        "--webroot",
        "-w /var/www/letsencrypt",
        "--non-interactive",
        "--agree-tos",
    ]
    
    cmd_parts.append(f"--cert-name {shlex.quote(cert_name)}")
    
    for domain in domains:
        cmd_parts.append(f"-d {shlex.quote(domain)}")
    
    if email:
        cmd_parts.append(f"--email {shlex.quote(email)}")
    else:
        cmd_parts.append("--register-unsafely-without-email")
    
    cmd = " ".join(cmd_parts)
    
    result = run(cmd, check=False)
    
    if result.returncode == 0:
        print(f"  ✓ Certificate '{cert_name}' obtained")
        return True
    else:
        print(f"  ⚠ Failed to obtain certificate '{cert_name}'")
        return False


def create_domain_cert_links(domains: List[str], cert_name: str) -> None:
    """Create symlinks for each domain to shared certificate for easy SSL status checking."""
    cert_dir = f"/etc/letsencrypt/live/{cert_name}"
    
    if not os.path.exists(cert_dir):
        print(f"  ⚠ Certificate directory {cert_dir} not found")
        return
    
    for domain in domains:
        if domain == cert_name:
            continue
        
        link_path = f"/etc/letsencrypt/live/{domain}"
        
        if os.path.exists(link_path) or os.path.islink(link_path):
            if os.path.islink(link_path):
                target = os.readlink(link_path)
                if target == cert_name:
                    continue
                target_abs = os.path.join(os.path.dirname(link_path), target) if not os.path.isabs(target) else target
                if os.path.normpath(target_abs) == os.path.normpath(cert_dir):
                    continue
            else:
                print(f"  ⚠ {link_path} exists but is not a symlink, skipping")
                continue
        
        try:
            os.symlink(cert_name, link_path)
            print(f"  ✓ Created symlink: {domain} -> {cert_name}")
        except Exception as e:
            print(f"  ⚠ Failed to create symlink for {domain}: {e}")


def setup_certificate_renewal() -> None:
    print("  Setting up automatic certificate renewal...")
    
    run("systemctl enable certbot.timer", check=False)
    run("systemctl start certbot.timer", check=False)
    
    print("  ✓ Automatic renewal configured")


def setup_ssl_for_deployments(deployments: List[dict], email: Optional[str] = None) -> None:
    """
    Set up Let's Encrypt SSL using SANs for all deployed domains.
    Requests single certificate covering all domains for efficiency.
    """
    print("\n" + "=" * 60)
    print("Setting up Let's Encrypt SSL certificates...")
    print("=" * 60)
    
    domains = set()
    for dep in deployments:
        domain = dep.get('domain')
        if domain:
            domains.add(domain)
            
            if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                if not dep.get('path') or dep.get('path') == '/':
                    domains.add(f"api.{domain}")
    
    if not domains:
        print("  No domains to configure SSL for (only local path deployments)")
        return
    
    domain_list = sorted(domains)
    
    print(f"  Requesting certificate for {len(domain_list)} domain(s) using Subject Alternative Names")
    
    cert_name = domain_list[0]
    
    if len(domain_list) > 100:
        print(f"  ⚠ Warning: {len(domain_list)} domains exceeds Let's Encrypt limit of 100 SANs")
        print(f"  ⚠ Only the first 100 domains will be included in the certificate")
        domain_list = domain_list[:100]
    
    success = obtain_letsencrypt_certificate(domain_list, email, cert_name)
    
    if not success:
        print("  ⚠ Failed to obtain certificate")
        return
    
    print(f"  Creating symbolic links for domain certificate references...")
    create_domain_cert_links(domain_list, cert_name)
    
    print("\n  Regenerating nginx configurations to use Let's Encrypt certificates...")
    
    from collections import defaultdict
    from shared.nginx_config import create_nginx_sites_for_groups
    
    grouped_deployments = defaultdict(list)
    for dep in deployments:
        grouped_deployments[dep['domain']].append(dep)
    
    create_nginx_sites_for_groups(grouped_deployments)
    
    setup_certificate_renewal()
    
    print("  ✓ SSL setup complete")
    print(f"  ✓ Single certificate covers all {len(domain_list)} domain(s)")
