"""Nginx configuration generator for deployed applications."""

import os
import shlex
from typing import Optional, Callable, List, Dict


SSL_PROTOCOLS = "TLSv1.2 TLSv1.3"
SSL_CIPHERS = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"


def get_ssl_cert_path(domain: Optional[str]) -> tuple:
    """Get SSL certificate and key paths for a domain."""
    cert_name = domain or 'default'
    cert_file = f"/etc/nginx/ssl/{cert_name}.crt"
    key_file = f"/etc/nginx/ssl/{cert_name}.key"
    return (cert_file, key_file)


def generate_self_signed_cert(domain: str, run_func: Callable) -> tuple:
    """Generate self-signed SSL certificate for a domain."""
    cert_file, key_file = get_ssl_cert_path(domain)
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        return (cert_file, key_file)
    
    cert_dir = os.path.dirname(cert_file)
    run_func(f"mkdir -p {cert_dir}")
    run_func(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 "
             f"-keyout {shlex.quote(key_file)} -out {shlex.quote(cert_file)} "
             f"-subj '/CN={domain}'")
    
    return (cert_file, key_file)


def generate_merged_nginx_config(domain: Optional[str], deployments: List[Dict], is_default: bool = False) -> str:
    """Generate a merged nginx configuration for multiple deployments on the same domain."""
    cert_file, key_file = get_ssl_cert_path(domain)
    server_name_directive = f"server_name {domain};" if domain else "server_name _;"
    default_server = " default_server" if is_default else ""
    
    # Sort deployments: longest path first to ensure correct matching in nginx
    sorted_deployments = sorted(deployments, key=lambda d: len(d['path']), reverse=True)
    
    # Check if we have any API subdomains to handle separately
    api_configs = []
    if domain:
        for dep in sorted_deployments:
            if dep.get('backend_port') and dep.get('frontend_port'):
                # Subdomain strategy for Rails apps with domain
                api_domain = f"api.{domain}"
                api_cert, api_key = get_ssl_cert_path(api_domain)
                backend_port = dep['backend_port']
                
                api_configs.append(f"""server {{
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    
    server_name {api_domain};
    
    ssl_certificate {api_cert};
    ssl_certificate_key {api_key};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_prefer_server_ciphers on;
    ssl_ciphers {SSL_CIPHERS};
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    location / {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
""")

    # Main Server Block
    locations = []
    
    # Add ACME challenge location
    locations.append("""    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }""")
    
    for dep in sorted_deployments:
        path = dep['path']
        location_path = path.rstrip('/') if path != '/' else '/'
        
        if dep['needs_proxy']:
            backend_port = dep.get('backend_port')
            frontend_port = dep.get('frontend_port')
            proxy_port = dep.get('proxy_port') or 3000 # Fallback
            
            if backend_port and frontend_port:
                if domain:
                    # Subdomain strategy: Frontend only in main block
                    if location_path == '/':
                        locations.append(f"""    # Frontend for {path}
    location / {{
        proxy_pass http://127.0.0.1:{frontend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}""")
                    else:
                        locations.append(f"""    # Frontend for {path}
    location {location_path}/ {{
        proxy_pass http://127.0.0.1:{frontend_port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    
    # Redirect {location_path} to {location_path}/
    location = {location_path} {{
        return 301 {location_path}/;
    }}""")
                else:
                    # Subpath strategy: Backend at /path/api, Frontend at /path
                    # Determine API path
                    if location_path == '/':
                        api_path = "/api/"
                    else:
                        api_path = f"{location_path}/api/"
                    
                    backend_block = f"""    # Backend for {path}
    location {api_path} {{
        proxy_pass http://127.0.0.1:{backend_port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}"""

                    if location_path == '/':
                        frontend_block = f"""    # Frontend for {path}
    location / {{
        proxy_pass http://127.0.0.1:{frontend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}"""
                    else:
                        frontend_block = f"""    # Frontend for {path}
    location {location_path}/ {{
        proxy_pass http://127.0.0.1:{frontend_port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    
    # Redirect {location_path} to {location_path}/
    location = {location_path} {{
        return 301 {location_path}/;
    }}"""
                    
                    locations.append(backend_block + "\n\n" + frontend_block)
            else:
                # Simple proxy (Node only or Rails API only?)
                if location_path == '/':
                    locations.append(f"""    # Proxy for {path}
    location / {{
        proxy_pass http://127.0.0.1:{proxy_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}""")
                else:
                    locations.append(f"""    # Proxy for {path}
    location {location_path}/ {{
        proxy_pass http://127.0.0.1:{proxy_port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    # Redirect {location_path} to {location_path}/
    location = {location_path} {{
        return 301 {location_path}/;
    }}""")
        else:
            # Static site
            serve_path = dep['serve_path']
            index_file = "index.html index.htm"
            
            if location_path == '/':
                # Root location uses 'root' directive usually, but we can't use 'root' globally if we have aliases.
                # Actually, we can use 'root' inside location /.
                locations.append(f"""    # Static site for {path}
    location / {{
        root {serve_path};
        index {index_file};
        autoindex off;
        charset utf-8;
        try_files $uri $uri.html $uri.htm $uri/ =404;
    }}""")
            else:
                locations.append(f"""    # Static site for {path}
    location {location_path} {{
        alias {serve_path};
        index {index_file};
        autoindex off;
        charset utf-8;
        try_files $uri $uri.html $uri.htm $uri/ =404;
    }}""")

    # Add deny rules
    locations.append("""    location ~ /\\. {
        deny all;
        access_log off;
        log_not_found off;
    }""")

    main_config = f"""server {{
    listen 80{default_server};
    listen [::]:80{default_server};
    listen 443 ssl http2{default_server};
    listen [::]:443 ssl http2{default_server};
    
    {server_name_directive}
    
    ssl_certificate {cert_file};
    ssl_certificate_key {key_file};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_prefer_server_ciphers on;
    ssl_ciphers {SSL_CIPHERS};
    
{chr(10).join(locations)}
}}
"""
    
    return "\n".join(api_configs + [main_config])


def create_nginx_sites_for_groups(grouped_deployments: Dict[Optional[str], List[Dict]], run_func: Callable) -> None:
    """Create nginx site configurations for grouped deployments."""
    
    run_func("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    for domain, deployments in grouped_deployments.items():
        cert_domain = domain or 'default'
        generate_self_signed_cert(cert_domain, run_func)
        
        if domain:
            # Check for API subdomains
            for dep in deployments:
                if dep.get('backend_port') and dep.get('frontend_port'):
                    generate_self_signed_cert(f"api.{domain}", run_func)
            
            config_name = domain.replace('.', '_')
        else:
            config_name = "default"
            
        config_file = f"/etc/nginx/sites-available/{config_name}"
        
        # Determine if this is the default server
        is_default = (domain is None)
        
        config_content = generate_merged_nginx_config(domain, deployments, is_default)
        
        try:
            with open(config_file, 'w') as f:
                f.write(config_content)
        except PermissionError as e:
            print(f"  ⚠ Failed to write nginx config to {config_file}: {e}")
            continue
        
        print(f"  ✓ Created nginx config: {config_file}")
        
        enabled_link = f"/etc/nginx/sites-enabled/{config_name}"
        if not os.path.exists(enabled_link):
            run_func(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
            print(f"  ✓ Enabled nginx site: {config_name}")
            
    result = run_func("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed")
        # Don't remove files immediately to allow debugging, but maybe warn loudly
    else:
        run_func("systemctl reload nginx")
        print(f"  ✓ nginx reloaded")


def create_nginx_site(*args, **kwargs):
    print("  ⚠ Warning: create_nginx_site is deprecated, use create_nginx_sites_for_groups")
    pass


