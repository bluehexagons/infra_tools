"""Web server setup steps."""

import os

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed, is_service_active, file_contains


def install_nginx(config: SetupConfig) -> None:
    if is_package_installed("nginx"):
        if is_service_active("nginx"):
            print("  ✓ nginx already installed and running")
            return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq nginx")
    
    run("systemctl enable nginx")
    run("systemctl start nginx")
    
    print("  ✓ nginx installed and started")


def configure_nginx_security(config: SetupConfig) -> None:
    nginx_conf = "/etc/nginx/nginx.conf"
    
    if file_contains(nginx_conf, "server_tokens off"):
        print("  ✓ nginx security already configured")
        return
    
    if not os.path.exists("/etc/nginx/nginx.conf.bak"):
        run("cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak")
    
    config_template_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
    template_path = os.path.join(config_template_dir, 'nginx.conf.template')
    with open(template_path, 'r', encoding='utf-8') as f:
        nginx_security_conf = f.read()
    
    with open(nginx_conf, "w") as f:
        f.write(nginx_security_conf)
    
    print("  ✓ nginx security configuration applied")


def create_hello_world_site(config: SetupConfig) -> None:
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


def configure_default_site(config: SetupConfig) -> None:
    site_conf = "/etc/nginx/sites-available/default"
    
    if os.path.exists(site_conf):
        if file_contains(site_conf, "Hello World"):
            print("  ✓ Default site already configured")
            return
    
    config_template_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
    template_path = os.path.join(config_template_dir, 'nginx_default_site.conf.template')
    with open(template_path, 'r', encoding='utf-8') as f:
        default_site = f.read()
    
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
