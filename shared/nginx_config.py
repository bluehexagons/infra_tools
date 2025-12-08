"""Nginx configuration generator for deployed applications."""

import os
import shlex
from typing import Optional


def generate_nginx_config(domain: str, path: str, serve_path: str, 
                         needs_proxy: bool, proxy_port: Optional[int] = None) -> str:
    """
    Generate nginx configuration for a deployed application.
    
    Args:
        domain: Domain name (e.g., "my.example.com")
        path: URL path (e.g., "/blog")
        serve_path: Filesystem path to serve
        needs_proxy: Whether to use reverse proxy
        proxy_port: Port for reverse proxy (if needs_proxy is True)
    
    Returns:
        Nginx configuration string
    """
    # Normalize path
    location_path = path.rstrip('/') if path != '/' else '/'
    
    if needs_proxy:
        # Reverse proxy configuration (for Rails apps)
        if not proxy_port:
            proxy_port = 3000  # Default Rails port
        
        config = f"""# Configuration for {domain}{location_path}
server {{
    listen 80;
    listen [::]:80;
    
    server_name {domain};
    
    location {location_path} {{
        proxy_pass http://127.0.0.1:{proxy_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
    else:
        # Static file serving configuration
        index_file = "index.html index.htm"
        
        if location_path == '/':
            # Root path - simple configuration
            config = f"""# Configuration for {domain}
server {{
    listen 80;
    listen [::]:80;
    
    server_name {domain};
    
    root {serve_path};
    index {index_file};
    
    # Disable directory listing
    autoindex off;
    
    location / {{
        try_files $uri $uri/ =404;
    }}
    
    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
    
    # Deny access to backup files
    location ~ ~$ {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
        else:
            # Sub-path - use alias
            config = f"""# Configuration for {domain}{location_path}
server {{
    listen 80;
    listen [::]:80;
    
    server_name {domain};
    
    location {location_path} {{
        alias {serve_path};
        index {index_file};
        try_files $uri $uri/ =404;
    }}
    
    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
        access_log off;
        log_not_found off;
    }}
}}
"""
    
    return config


def create_nginx_site(domain: str, path: str, serve_path: str,
                     needs_proxy: bool, proxy_port: Optional[int], run_func) -> str:
    """
    Create an nginx site configuration file.
    
    Args:
        domain: Domain name
        path: URL path
        serve_path: Filesystem path to serve
        needs_proxy: Whether to use reverse proxy
        proxy_port: Port for reverse proxy
        run_func: Function to run commands
    
    Returns:
        Path to the created configuration file
    """
    # Generate safe config filename from domain and path
    safe_domain = domain.replace('.', '_')
    safe_path = path.strip('/').replace('/', '_')
    
    if safe_path:
        config_name = f"{safe_domain}_{safe_path}"
    else:
        config_name = safe_domain
    
    config_file = f"/etc/nginx/sites-available/{config_name}"
    
    # Generate configuration
    config_content = generate_nginx_config(domain, path, serve_path, needs_proxy, proxy_port)
    
    # Write configuration file
    try:
        with open(config_file, 'w') as f:
            f.write(config_content)
    except PermissionError as e:
        raise PermissionError(f"Failed to write nginx config to {config_file}. Need root permissions.") from e
    except OSError as e:
        raise OSError(f"Failed to create nginx config file {config_file}: {e}") from e
    
    print(f"  ✓ Created nginx config: {config_file}")
    
    # Enable the site
    enabled_link = f"/etc/nginx/sites-enabled/{config_name}"
    if not os.path.exists(enabled_link):
        run_func(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
        print(f"  ✓ Enabled nginx site: {config_name}")
    
    # Test nginx configuration
    result = run_func("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed")
        # Remove the bad config
        if os.path.exists(enabled_link):
            os.remove(enabled_link)
        if os.path.exists(config_file):
            os.remove(config_file)
        raise ValueError("Invalid nginx configuration - test failed")
    
    # Reload nginx
    run_func("systemctl reload nginx")
    print(f"  ✓ nginx reloaded")
    
    return config_file
