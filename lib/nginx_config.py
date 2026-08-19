"""Nginx configuration generator for deployed applications."""

from __future__ import annotations

import os
import shlex
import shutil
from typing import Optional

from lib.types import Deployments, StrList, PathPair
from lib.remote_utils import run


SSL_PROTOCOLS = "TLSv1.2 TLSv1.3"
SSL_CIPHERS = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
NGINX_SITES_AVAILABLE_DIR = "/etc/nginx/sites-available"
NGINX_SITES_ENABLED_DIR = "/etc/nginx/sites-enabled"
PRESERVED_SITE_PREFIXES = ("antistatic_", "gogs_")
GENERATED_CONFIG_MARKER = "# Managed by infra_tools deployment nginx generator"


def _config_name_for_domain(domain: Optional[str]) -> str:
    return domain.replace('.', '_') if domain else 'default'


def _remove_path(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _is_infra_tools_deployment_site(path: str) -> bool:
    read_path = os.path.realpath(path) if os.path.islink(path) else path
    try:
        with open(read_path, 'r', encoding='utf-8') as handle:
            content = handle.read()
    except OSError:
        return False

    if GENERATED_CONFIG_MARKER in content:
        return True

    # Legacy generated deployment configs predate the explicit marker. Keep the
    # heuristic narrow so unrelated nginx sites are not swept up.
    return all(token in content for token in (
        "map $uri $assets_expires_",
        "map $uri $assets_cc_",
        "location /.well-known/acme-challenge/",
        "add_header Strict-Transport-Security",
    ))


def _reconcile_deployment_sites(current_config_names: set[str]) -> None:
    """Remove stale app deployment nginx sites before writing current ones.

    App deployments own unprefixed ``sites-available``/``sites-enabled`` names
    such as ``example_com`` and ``default``. Prefix-owned service configs (Gogs,
    antistatic) are managed by their own setup steps and must be left alone.
    """
    for directory in (NGINX_SITES_ENABLED_DIR, NGINX_SITES_AVAILABLE_DIR):
        if not os.path.isdir(directory):
            continue

        for name in os.listdir(directory):
            if name in current_config_names or name.startswith(PRESERVED_SITE_PREFIXES):
                continue

            path = os.path.join(directory, name)
            if not _is_infra_tools_deployment_site(path):
                continue

            try:
                _remove_path(path)
            except OSError as e:
                raise RuntimeError(f"Failed to remove stale nginx config {path}: {e}") from e
            else:
                print(f"  ✓ Removed stale nginx config: {path}")


def _snapshot_deployment_sites(current_config_names: set[str]) -> dict[str, tuple[str, object]]:
    snapshot: dict[str, tuple[str, object]] = {}
    for directory in (NGINX_SITES_AVAILABLE_DIR, NGINX_SITES_ENABLED_DIR):
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if name not in current_config_names and not _is_infra_tools_deployment_site(path):
                continue
            if os.path.islink(path):
                snapshot[path] = ("symlink", os.readlink(path))
            elif os.path.isfile(path):
                with open(path, "rb") as handle:
                    snapshot[path] = ("file", (handle.read(), os.stat(path).st_mode & 0o777))
    return snapshot


def _restore_deployment_sites(
    snapshot: dict[str, tuple[str, object]],
    current_config_names: set[str],
) -> None:
    for directory in (NGINX_SITES_ENABLED_DIR, NGINX_SITES_AVAILABLE_DIR):
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if name in current_config_names or _is_infra_tools_deployment_site(path):
                _remove_path(path)
    for path, (kind, value) in snapshot.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if kind == "symlink":
            os.symlink(str(value), path)
        else:
            content, mode = value
            with open(path, "wb") as handle:
                handle.write(content)
            os.chmod(path, mode)


def get_ssl_cert_path(domain: Optional[str]) -> PathPair:
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


def generate_self_signed_cert(domain: str) -> PathPair:
    """Generate self-signed SSL certificate for a domain."""
    cert_file, key_file = get_ssl_cert_path(domain)
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        return (cert_file, key_file)
    
    cert_dir = os.path.dirname(cert_file)
    run(f"mkdir -p {cert_dir}")
    run(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 "
             f"-keyout {shlex.quote(key_file)} -out {shlex.quote(cert_file)} "
             f"-subj '/CN={domain}'")
    
    return (cert_file, key_file)


def _make_cache_maps(domain_slug: str) -> tuple[str, str, str]:
    """Generate map blocks for caching and return variable names."""
    expires_var = f"$assets_expires_{domain_slug}"
    cc_var = f"$assets_cc_{domain_slug}"
    
    maps = fr"""
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
                        expires_var: Optional[str] = None, cc_var: Optional[str] = None,
                        forwarded_proto: str = "$scheme", enable_path_redirect: bool = True,
                        preserve_path: bool = False) -> str:
    """Generate a proxy_pass location block."""
    slash = "" if preserve_path or path == "/" else "/"
    
    content = [
        f"        proxy_pass http://127.0.0.1:{port}{slash};",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        f"        proxy_set_header X-Forwarded-Proto {forwarded_proto};",
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
        exact_location = f"""    # Redirect {path} to {path}/
    location = {path} {{
        return 301 {path}/;
    }}""" if enable_path_redirect else f"""    # Proxy exact {path} without redirect
    location = {path} {{
{body}
    }}"""
        return f"""    {comment}
    location {path}/ {{
{body}
    }}

{exact_location}"""


def _make_static_location(path: str, serve_path: str, index_file: str, try_files: str, comment: str,
                         expires_var: Optional[str] = None, cc_var: Optional[str] = None) -> str:
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


def _make_api_server_block(
    domain: str,
    port: int,
    enable_https_redirect: bool = True,
    forwarded_proto: str = "$scheme",
) -> str:
    """Generate a separate server block for API subdomain (HTTP redirect + HTTPS)."""
    cert, key = get_ssl_cert_path(domain)
    redirect_block = """
    location / {
        return 301 https://$host$request_uri;
    }
""" if enable_https_redirect else f"""
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto {forwarded_proto};
        proxy_buffering on;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_intercept_errors off;
    }}
"""
    return f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
{redirect_block}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name {domain};
    
    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_prefer_server_ciphers on;
    ssl_ciphers {SSL_CIPHERS};
    
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto {forwarded_proto};

        # Performance optimizations for API backends
        proxy_buffering on;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_intercept_errors off;
    }}
}}
"""


def generate_merged_nginx_config(
    domain: Optional[str],
    deployments: Deployments,
    is_default: bool = False,
    enable_https_redirect: bool = True,
) -> str:
    """Generate a merged nginx configuration for multiple deployments on the same domain."""
    cert_file, key_file = get_ssl_cert_path(domain)
    server_name_directive = f"server_name {domain};" if domain else "server_name _;"
    default_server = " default_server" if is_default else ""
    
    domain_slug = _config_name_for_domain(domain)
    cache_maps, expires_var, cc_var = _make_cache_maps(domain_slug)
    forwarded_proto = "https" if not enable_https_redirect else "$scheme"
    enable_path_redirect = enable_https_redirect
    
    sorted_deployments = sorted(deployments, key=lambda d: len(d['path']), reverse=True)
    
    api_configs: StrList = []
    if domain:
        for dep in sorted_deployments:
            if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                use_subdomain = dep.get('api_subdomain', False)
                
                if (dep['path'] == '/' or not dep['path']) and use_subdomain:
                    api_domain = f"api.{domain}"
                    api_configs.append(_make_api_server_block(
                        api_domain,
                        dep['backend_port'],
                        enable_https_redirect=enable_https_redirect,
                        forwarded_proto=forwarded_proto,
                    ))

    locations: StrList = []
    
    locations.append("""    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }""")
    
    for dep in sorted_deployments:
        path = dep['path']
        location_path = path.rstrip('/') if path != '/' else '/'
        
        if dep['needs_proxy']:
            backend_port = dep.get('backend_port')
            frontend_port = dep.get('frontend_port')
            proxy_port = dep.get('proxy_port') or backend_port or 3000
            frontend_serve_path = dep.get('frontend_serve_path')
            
            if backend_port and (frontend_port or frontend_serve_path):
                use_subdomain_api = domain and (path == '/' or not path) and dep.get('api_subdomain', False)
                
                if use_subdomain_api:
                    if frontend_serve_path:
                        try_files = "$uri $uri.html $uri/ /index.html" if location_path == '/' else f"$uri $uri.html $uri/ {location_path}/index.html"
                        locations.append(_make_static_location(
                            location_path, frontend_serve_path, "index.html", try_files, f"# Frontend for {path}",
                            expires_var=expires_var, cc_var=cc_var
                        ))
                    else:
                        if frontend_port is not None:
                            locations.append(_make_proxy_location(
                                location_path, frontend_port, f"# Frontend for {path}", enable_websocket=True,
                                expires_var=expires_var, cc_var=cc_var,
                                forwarded_proto=forwarded_proto, enable_path_redirect=enable_path_redirect
                            ))
                        else:
                            raise ValueError("frontend_port must be set to create proxy location")
                else:
                    # Subpath strategy: Backend at /path/api, Frontend at /path
                    
                    api_path = "/api" if location_path == '/' else f"{location_path}/api"
                    locations.append(_make_proxy_location(
                        api_path, backend_port, f"# Backend for {path}",
                        expires_var=expires_var, cc_var=cc_var,
                        forwarded_proto=forwarded_proto, enable_path_redirect=enable_path_redirect
                    ))

                    if frontend_serve_path:
                        try_files = "$uri $uri.html $uri/ /index.html" if location_path == '/' else f"$uri $uri.html $uri/ {location_path}/index.html"
                        locations.append(_make_static_location(
                            location_path, frontend_serve_path, "index.html", try_files, f"# Frontend for {path}",
                            expires_var=expires_var, cc_var=cc_var
                        ))
                    else:
                        if frontend_port is not None:
                            locations.append(_make_proxy_location(
                                location_path, frontend_port, f"# Frontend for {path}", enable_websocket=True,
                                expires_var=expires_var, cc_var=cc_var,
                                forwarded_proto=forwarded_proto, enable_path_redirect=enable_path_redirect
                            ))
                        else:
                            raise ValueError("frontend_port must be set to create proxy location")
            else:
                locations.append(_make_proxy_location(
                    location_path, proxy_port, f"# Proxy for {path}",
                    expires_var=expires_var, cc_var=cc_var,
                    forwarded_proto=forwarded_proto, enable_path_redirect=enable_path_redirect,
                    preserve_path=dep.get('preserve_path', False)
                ))
        else:
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

    locations.append("""    location ~ /\\. {
        deny all;
        access_log off;
        log_not_found off;
    }""")

    acme_location = locations[0]
    http_content = f"""
{acme_location}

    location / {{
        return 301 https://$host$request_uri;
    }}
""" if enable_https_redirect else f"""
{chr(10).join(locations)}
"""

    main_config = f"""server {{
    listen 80{default_server};
    listen [::]:80{default_server};

    {server_name_directive}
{http_content}
}}

server {{
    listen 443 ssl{default_server};
    listen [::]:443 ssl{default_server};
    http2 on;

    {server_name_directive}

    ssl_certificate {cert_file};
    ssl_certificate_key {key_file};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_prefer_server_ciphers on;
    ssl_ciphers {SSL_CIPHERS};

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

{chr(10).join(locations)}
}}
"""
    
    return "\n".join([GENERATED_CONFIG_MARKER, cache_maps] + api_configs + [main_config])


def _create_nginx_sites_for_groups(
    grouped_deployments: dict[Optional[str], Deployments],
    enable_https_redirect: bool = True,
) -> None:
    """Create nginx site configurations for grouped deployments."""
    
    run("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    current_config_names = {_config_name_for_domain(domain) for domain in grouped_deployments}
    _reconcile_deployment_sites(current_config_names)
    
    for domain, deployments in grouped_deployments.items():
        cert_domain = domain or 'default'
        generate_self_signed_cert(cert_domain)
        
        if domain:
            # Check for API subdomains
            for dep in deployments:
                if dep.get('backend_port') and (dep.get('frontend_port') or dep.get('frontend_serve_path')):
                    if dep.get('api_subdomain', False):
                        generate_self_signed_cert(f"api.{domain}")
            
            config_name = _config_name_for_domain(domain)
        else:
            config_name = _config_name_for_domain(domain)

        config_file = os.path.join(NGINX_SITES_AVAILABLE_DIR, config_name)
        
        is_default = (domain is None)
        
        config_content = generate_merged_nginx_config(
            domain, deployments, is_default, enable_https_redirect=enable_https_redirect
        )
        
        try:
            with open(config_file, 'w') as f:
                f.write(config_content)
        except PermissionError as e:
            raise PermissionError(f"Failed to write nginx config to {config_file}: {e}") from e
        
        print(f"  ✓ Created nginx config: {config_file}")
        
        enabled_link = os.path.join(NGINX_SITES_ENABLED_DIR, config_name)
        if os.path.lexists(enabled_link) and (
            not os.path.islink(enabled_link) or os.path.realpath(enabled_link) != config_file
        ):
            _remove_path(enabled_link)

        if not os.path.lexists(enabled_link):
            run(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
            print(f"  ✓ Enabled nginx site: {config_name}")
            
    result = run("nginx -t", check=False)
    if result.returncode != 0:
        raise RuntimeError("nginx configuration test failed")
    run("systemctl reload nginx")
    print(f"  ✓ nginx reloaded")


def create_nginx_sites_for_groups(
    grouped_deployments: dict[Optional[str], Deployments],
    enable_https_redirect: bool = True,
) -> None:
    """Atomically replace deployment-owned Nginx sites after validation."""
    current_config_names = {_config_name_for_domain(domain) for domain in grouped_deployments}
    snapshot = _snapshot_deployment_sites(current_config_names)
    try:
        _create_nginx_sites_for_groups(
            grouped_deployments,
            enable_https_redirect=enable_https_redirect,
        )
    except Exception:
        _restore_deployment_sites(snapshot, current_config_names)
        validation = run("nginx -t", check=False)
        if validation.returncode != 0:
            print("  ⚠ Restored previous Nginx files, but their validation also failed")
        else:
            print("  ✓ Restored previous Nginx configuration")
        raise
