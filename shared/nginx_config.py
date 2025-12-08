"""Nginx configuration generator for deployed applications."""

import os
import shlex
from typing import Optional, Callable


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


def generate_nginx_config(domain: Optional[str], path: str, serve_path: str, 
                         needs_proxy: bool, proxy_port: Optional[int] = None,
                         backend_port: Optional[int] = None, frontend_port: Optional[int] = None,
                         is_default: bool = False) -> str:
    """Generate nginx configuration for a deployed application."""
    location_path = path.rstrip('/') if path != '/' else '/'
    
    cert_file, key_file = get_ssl_cert_path(domain)
    
    if needs_proxy:
        server_name_directive = f"server_name {domain};" if domain else "server_name _;"
        default_server = " default_server" if is_default else ""
        
        # Dual proxy configuration (Rails + Node)
        if backend_port and frontend_port:
            if domain:
                # Subdomain strategy: api.domain.com -> Backend, domain.com -> Frontend
                api_domain = f"api.{domain}"
                api_cert, api_key = get_ssl_cert_path(api_domain)
                
                # API Server Block
                api_config = f"""server {{
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
"""
                # Frontend Server Block
                frontend_config = f"""server {{
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
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
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
    }}
    
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
                return f"{api_config}\n{frontend_config}"
            
            else:
                # Subpath strategy: /api -> Backend, / -> Frontend
                config = f"""server {{
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
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    # Backend API routes (rewrite /api/x -> /x)
    location /api/ {{
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    # Frontend
    location {location_path} {{
        proxy_pass http://127.0.0.1:{frontend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
        else:
            if not proxy_port:
                proxy_port = 3000
            
            config = f"""server {{
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
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    location {location_path} {{
        proxy_pass http://127.0.0.1:{proxy_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
    else:
        index_file = "index.html index.htm"
        server_name_directive = f"server_name {domain};" if domain else "server_name _;"
        default_server = " default_server" if is_default else ""
        
        if location_path == '/':
            config = f"""server {{
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
    
    root {serve_path};
    index {index_file};
    autoindex off;
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    location / {{
        try_files $uri $uri/ =404;
    }}
    
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
    
    location ~ ~$ {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
        else:
            config = f"""server {{
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
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    location {location_path} {{
        alias {serve_path};
        index {index_file};
        try_files $uri $uri/ =404;
    }}
    
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
    
    return config


def create_nginx_site(domain: Optional[str], path: str, serve_path: str,
                     needs_proxy: bool, proxy_port: Optional[int], run_func: Callable,
                     is_default: bool = False,
                     backend_port: Optional[int] = None, frontend_port: Optional[int] = None) -> str:
    """Create an nginx site configuration file."""
    cert_domain = domain or 'default'
    
    run_func("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    cert_file, key_file = generate_self_signed_cert(cert_domain, run_func)
    
    if domain and backend_port and frontend_port:
        # Generate cert for api subdomain too
        generate_self_signed_cert(f"api.{domain}", run_func)
    
    if domain:
        safe_domain = domain.replace('.', '_')
        safe_path = path.strip('/').replace('/', '_')
        config_name = f"{safe_domain}_{safe_path}" if safe_path else safe_domain
    else:
        config_name = "default"
    
    config_file = f"/etc/nginx/sites-available/{config_name}"
    
    config_content = generate_nginx_config(domain, path, serve_path, needs_proxy, proxy_port, 
                                         backend_port, frontend_port, is_default)
    
    try:
        with open(config_file, 'w') as f:
            f.write(config_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write nginx config to {config_file}. Need root permissions.") from e
    except OSError as e:
        raise OSError(f"Failed to create nginx config file {config_file}: {e}") from e
    
    print(f"  ✓ Created nginx config: {config_file}")
    
    enabled_link = f"/etc/nginx/sites-enabled/{config_name}"
    if not os.path.exists(enabled_link):
        run_func(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
        print(f"  ✓ Enabled nginx site: {config_name}")
    
    result = run_func("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed")
        if os.path.exists(enabled_link):
            os.remove(enabled_link)
        if os.path.exists(config_file):
            os.remove(config_file)
        raise ValueError("Invalid nginx configuration - test failed")
    
    run_func("systemctl reload nginx")
    print(f"  ✓ nginx reloaded")
    
    return config_file


