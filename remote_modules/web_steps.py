"""Web server setup steps."""

import os

from .utils import run, is_package_installed, is_service_active, file_contains


def install_nginx(os_type: str, **_) -> None:
    if is_package_installed("nginx", os_type):
        if is_service_active("nginx"):
            print("  ✓ nginx already installed and running")
            return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq nginx")
    
    run("systemctl enable nginx")
    run("systemctl start nginx")
    
    print("  ✓ nginx installed and started")


def configure_nginx_security(os_type: str, **_) -> None:
    nginx_conf = "/etc/nginx/nginx.conf"
    
    if file_contains(nginx_conf, "server_tokens off"):
        print("  ✓ nginx security already configured")
        return
    
    if not os.path.exists("/etc/nginx/nginx.conf.bak"):
        run("cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak")
    
    # Create a security-hardened nginx configuration
    nginx_security_conf = """user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 768;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    types_hash_max_size 2048;
    
    # Security: Hide nginx version
    server_tokens off;
    
    # Security: Disable unwanted HTTP methods
    # This is handled per-server block
    
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # SSL Settings (for when SSL is configured)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    
    # Logging Settings
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    
    # Gzip Settings
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss application/rss+xml font/truetype font/opentype application/vnd.ms-fontobject image/svg+xml;
    
    # Caching Settings
    open_file_cache max=1000 inactive=20s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;
    
    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    
    # Virtual Host Configs
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
"""
    
    with open(nginx_conf, "w") as f:
        f.write(nginx_security_conf)
    
    print("  ✓ nginx security configuration applied")


def create_hello_world_site(os_type: str, **_) -> None:
    www_root = "/var/www/html"
    index_html = f"{www_root}/index.html"
    
    if os.path.exists(index_html):
        if file_contains(index_html, "Hello World"):
            print("  ✓ Hello World page already exists")
            return
    
    os.makedirs(www_root, exist_ok=True)
    
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hello World</title>
</head>
<body>
    <h1>Hello World</h1>
</body>
</html>
"""
    
    with open(index_html, "w") as f:
        f.write(html_content)
    
    run("chown -R www-data:www-data /var/www/html", check=False)
    run("chmod -R 755 /var/www/html")
    
    print("  ✓ Hello World website created")


def configure_default_site(os_type: str, **_) -> None:
    site_conf = "/etc/nginx/sites-available/default"
    
    if os.path.exists(site_conf):
        if file_contains(site_conf, "Hello World"):
            print("  ✓ Default site already configured")
            return
    
    default_site = r"""# Default server configuration
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    
    root /var/www/html;
    index index.html index.htm;
    
    server_name _;
    
    # Disable directory listing
    autoindex off;
    
    location / {
        # Security: Limit HTTP methods to GET, HEAD, POST
        limit_except GET HEAD POST {
            deny all;
        }
        
        try_files $uri $uri/ =404;
    }
    
    # Deny access to hidden files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
    
    # Deny access to backup files
    location ~ ~$ {
        deny all;
        access_log off;
        log_not_found off;
    }
}
"""
    
    with open(site_conf, "w") as f:
        f.write(default_site)
    
    run("ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default", check=False)
    
    result = run("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed, reverting...")
        if os.path.exists("/etc/nginx/nginx.conf.bak"):
            run("cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf")
        return
    
    run("systemctl reload nginx")
    
    print("  ✓ Default site configured (static files only, no scripting)")
