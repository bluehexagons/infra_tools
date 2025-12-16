"""Nginx configuration generator for deployed applications."""

import os
import shlex
from typing import Optional, Callable, List, Dict


SSL_PROTOCOLS = "TLSv1.2 TLSv1.3"
SSL_CIPHERS = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"


def get_ssl_cert_path(domain: Optional[str]) -> tuple:
    """Get SSL certificate paths, preferring Let's Encrypt over self-signed."""
    cert_name = domain or 'default'
    
    if domain:
        letsencrypt_cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        letsencrypt_key = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        if os.path.exists(letsencrypt_cert) and os.path.exists(letsencrypt_key):
            return (letsencrypt_cert, letsencrypt_key)
    
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


def _make_cache_maps(domain_slug: str) -> tuple:
    """Generate map blocks for caching and return variable names."""
    expires_var = f"$assets_expires_{domain_slug}"
    cc_var = f"$assets_cc_{domain_slug}"
    
    maps = f"""
map $uri {expires_var} {{
    default                    off;
    ~*\.(jpg|jpeg|png|gif|webp|svg|ico)$  1y;
    ~*\.(mp4|webm|ogg|mov|avi|flv|wmv)$   1y;
    ~*\.(woff|woff2|ttf|eot|otf)$         1y;
    ~*\.(css|js)$                         1y;
    ~*\.(pdf|txt|xml|json)$               30d;
}}

map $uri {cc_var} {{
    default                    "";
    ~*\.(jpg|jpeg|png|gif|webp|svg|ico)$  "public, immutable";
    ~*\.(mp4|webm|ogg|mov|avi|flv|wmv)$   "public, immutable";
    ~*\.(woff|woff2|ttf|eot|otf)$         "public, immutable";
    ~*\.(css|js)$                         "public, immutable";
    ~*\.(pdf|txt|xml|json)$               "public";
}}
"""
    return maps, expires_var, cc_var


def _make_proxy_location(path: str, port: int, comment: str, enable_websocket: bool = False,
                        expires_var: str = None, cc_var: str = None) -> str:
    """Generate a proxy_pass location block."""
    slash = "/" if path != "/" else ""
    
    content = [
        f"        proxy_pass http://127.0.0.1:{port}{slash};",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "",
        "        # Performance optimizations for dynamic backends",
        "        proxy_buffering on;",
        "        proxy_intercept_errors off;"
    ]
    
    if enable_websocket:
        content.extend([
            "",
            "        # WebSocket support for Vite HMR",
            "        proxy_http_version 1.1;",
            "        proxy_set_header Upgrade $http_upgrade;",
            "        proxy_set_header Connection \"upgrade\";"
        ])
    else:
        content.extend([
            "",
            "        # Keepalive for backend connections",
            "        proxy_http_version 1.1;",
            "        proxy_set_header Connection \"\";"
        ])

    if expires_var:
        content.append(f"        expires {expires_var};")
    if cc_var:
        content.append(f"        add_header Cache-Control {cc_var};")
        
    body = "\n".join(content)
    
    if path == "/":
        return f"""    {comment}
    location / {{
{body}
    }}"""
    else:
        return f"""    {comment}
    location {path}/ {{
{body}
    }}
    
    # Redirect {path} to {path}/
    location = {path} {{
        return 301 {path}/;
    }}"""


def _make_static_location(path: str, serve_path: str, index_file: str, try_files: str, comment: str,
                         expires_var: str = None, cc_var: str = None) -> str:
    """Generate a static file serving location block."""
    directive = "root" if path == "/" else "alias"
    
    content = [
        f"        {directive} {serve_path};",
        f"        index {index_file};",
        "        autoindex off;",
        "        charset utf-8;",
        f"        try_files {try_files};"
    ]

    if expires_var:
        content.append(f"        expires {expires_var};")
    if cc_var:
        content.append(f"        add_header Cache-Control {cc_var};")

    body = "\n".join(content)
    
    return f"""    {comment}
    location {path} {{
{body}
    }}"""


def _make_api_server_block(domain: str, port: int) -> str:
    """Generate a separate server block for API subdomain."""
    cert, key = get_ssl_cert_path(domain)
    return f"""server {{
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    
    server_name {domain};
    
    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_prefer_server_ciphers on;
    ssl_ciphers {SSL_CIPHERS};
    
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Performance optimizations for API backends
        proxy_buffering on;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_intercept_errors off;
    }}
}}
"""


def generate_merged_nginx_config(domain: Optional[str], deployments: List[Dict], is_default: bool = False) -> str:
    """Generate a merged nginx configuration for multiple deployments on the same domain."""
    cert_file, key_file = get_ssl_cert_path(domain)
    server_name_directive = f"server_name {domain};" if domain else "server_name _;"
    default_server = " default_server" if is_default else ""
    
    # Generate cache maps
    domain_slug = domain.replace('.', '_') if domain else 'default'
    cache_maps, expires_var, cc_var = _make_cache_maps(domain_slug)
    
    # Sort deployments: longest path first to ensure correct matching in nginx
    sorted_deployments = sorted(deployments, key=lambda d: len(d['path']), reverse=True)
    
    # Check if we have any API subdomains to handle separately
    api_configs = []
    if domain:
        for dep in sorted_deployments:
            if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                # Subdomain strategy for Rails apps with domain - ONLY for root path
                # AND if api_subdomain is requested
                use_subdomain = dep.get('api_subdomain', False)
                
                if (dep['path'] == '/' or not dep['path']) and use_subdomain:
                    api_domain = f"api.{domain}"
                    api_configs.append(_make_api_server_block(api_domain, dep['backend_port']))

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
            frontend_serve_path = dep.get('frontend_serve_path')
            
            if backend_port and (frontend_port or frontend_serve_path):
                # Use subdomain strategy only if domain exists AND path is root AND api_subdomain is True
                use_subdomain_api = domain and (path == '/' or not path) and dep.get('api_subdomain', False)
                
                if use_subdomain_api:
                    # Subdomain strategy: Frontend only in main block
                    # Backend is handled by api_configs above
                    if frontend_serve_path:
                        # Static frontend
                        try_files = "$uri $uri.html $uri/ /index.html" if location_path == '/' else f"$uri $uri.html $uri/ {location_path}/index.html"
                        locations.append(_make_static_location(
                            location_path, frontend_serve_path, "index.html", try_files, f"# Frontend for {path}",
                            expires_var=expires_var, cc_var=cc_var
                        ))
                    else:
                        # Proxy frontend
                        locations.append(_make_proxy_location(
                            location_path, frontend_port, f"# Frontend for {path}", enable_websocket=True,
                            expires_var=expires_var, cc_var=cc_var
                        ))
                else:
                    # Subpath strategy: Backend at /path/api, Frontend at /path
                    
                    # Backend
                    api_path = "/api" if location_path == '/' else f"{location_path}/api"
                    locations.append(_make_proxy_location(
                        api_path, backend_port, f"# Backend for {path}",
                        expires_var=expires_var, cc_var=cc_var
                    ))

                    # Frontend
                    if frontend_serve_path:
                        try_files = "$uri $uri.html $uri/ /index.html" if location_path == '/' else f"$uri $uri.html $uri/ {location_path}/index.html"
                        locations.append(_make_static_location(
                            location_path, frontend_serve_path, "index.html", try_files, f"# Frontend for {path}",
                            expires_var=expires_var, cc_var=cc_var
                        ))
                    else:
                        locations.append(_make_proxy_location(
                            location_path, frontend_port, f"# Frontend for {path}", enable_websocket=True,
                            expires_var=expires_var, cc_var=cc_var
                        ))
            else:
                # Simple proxy
                locations.append(_make_proxy_location(
                    location_path, proxy_port, f"# Proxy for {path}",
                    expires_var=expires_var, cc_var=cc_var
                ))
        else:
            # Static site
            serve_path = dep['serve_path']
            index_file = "index.html index.htm"
            project_type = dep.get('project_type', 'static')
            
            try_files = "$uri $uri.html $uri.htm $uri/ =404"
            if project_type == 'node':
                 # Assume SPA
                 if location_path == '/':
                     try_files = "$uri $uri.html $uri/ /index.html"
                 else:
                     try_files = f"$uri $uri.html $uri/ {location_path}/index.html"
            
            locations.append(_make_static_location(
                location_path, serve_path, index_file, try_files, f"# Static site for {path}",
                expires_var=expires_var, cc_var=cc_var
            ))

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
    
    return "\n".join([cache_maps] + api_configs + [main_config])


def create_nginx_sites_for_groups(grouped_deployments: Dict[Optional[str], List[Dict]], run_func: Callable) -> None:
    """Create nginx site configurations for grouped deployments."""
    
    run_func("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    
    for domain, deployments in grouped_deployments.items():
        cert_domain = domain or 'default'
        generate_self_signed_cert(cert_domain, run_func)
        
        if domain:
            # Check for API subdomains
            for dep in deployments:
                if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                    if dep.get('api_subdomain', False):
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


