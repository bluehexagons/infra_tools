"""Setup steps for the antistatic lobby server.

Deploys the antistatic-server Go binary (https://github.com/bluehexagons/antistatic-server)
as a systemd service behind an nginx reverse proxy.
"""

from __future__ import annotations

import json
import os
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import SetupConfig

from lib.remote_utils import run, user_exists, is_service_active
from lib.systemd_service import cleanup_service


ANTISTATIC_USER = "antistatic"
ANTISTATIC_BINARY = "/usr/local/bin/antistatic-server"
ANTISTATIC_SERVICE = "antistatic"
GITHUB_REPO = "bluehexagons/antistatic-server"
DEFAULT_INTERNAL_PORT = 8080


def parse_antistatic_spec(spec: str) -> tuple[str, int]:
    """Parse a 'DOMAIN[:port]' spec into (domain, port).

    The port defaults to DEFAULT_INTERNAL_PORT when omitted or non-numeric.
    """
    if ":" in spec:
        domain, _, raw_port = spec.rpartition(":")
        try:
            return domain, int(raw_port)
        except ValueError:
            return domain, DEFAULT_INTERNAL_PORT
    return spec, DEFAULT_INTERNAL_PORT


def _detect_arch() -> str:
    """Return the GitHub release architecture suffix for this machine."""
    result = run("uname -m", capture_output=True)
    arch = result.stdout.strip() if result.stdout else "x86_64"
    if arch in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def _ensure_antistatic_user() -> None:
    """Create a dedicated antistatic system user if one does not already exist."""
    if user_exists(ANTISTATIC_USER):
        print(f"  ✓ System user already exists: {ANTISTATIC_USER}")
        return
    run(
        f"useradd --system --no-create-home --shell /usr/sbin/nologin "
        f"{ANTISTATIC_USER}"
    )
    print(f"  ✓ Created system user: {ANTISTATIC_USER}")


def _download_antistatic_binary(arch: str) -> None:
    """Download the latest antistatic-server release binary from GitHub.

    Raises RuntimeError if the download or the API call fails.
    """
    binary_name = f"antistatic-server-linux-{arch}"
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    result = run(
        f"curl -sf {shlex.quote(api_url)}",
        capture_output=True,
        display_cmd=f"curl -sf https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("Failed to fetch latest release info from GitHub")

    try:
        release_data = json.loads(result.stdout)
        assets = release_data.get("assets", [])
        download_url: str | None = next(
            (a["browser_download_url"] for a in assets if a["name"] == binary_name),
            None,
        )
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(f"Failed to parse GitHub release data: {exc}") from exc

    if not download_url:
        raise RuntimeError(
            f"No binary found for '{binary_name}' in the latest release of "
            f"https://github.com/{GITHUB_REPO}"
        )

    print(f"  Downloading {binary_name}...")
    tmp_path = f"/tmp/{binary_name}"
    run(
        f"curl -fL -o {shlex.quote(tmp_path)} {shlex.quote(download_url)}",
        check=True,
        display_cmd=f"curl -fL -o {tmp_path} <release URL>",
    )
    run(f"chmod +x {shlex.quote(tmp_path)}", check=True)
    run(f"mv {shlex.quote(tmp_path)} {ANTISTATIC_BINARY}", check=True)
    print(f"  ✓ Installed {ANTISTATIC_BINARY}")


def generate_antistatic_service(port: int) -> str:
    """Return systemd unit file content for the antistatic server."""
    return f"""\
[Unit]
Description=Antistatic lobby server
Documentation=https://github.com/bluehexagons/antistatic-server
After=network.target
Wants=network.target

[Service]
Type=simple
User={ANTISTATIC_USER}
Group={ANTISTATIC_USER}
ExecStart={ANTISTATIC_BINARY} -port {port} -trust-proxy
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
"""


def generate_antistatic_nginx_config(domain: str, port: int) -> str:
    """Return an nginx site config that proxies all traffic to the antistatic server."""
    from lib.nginx_config import SSL_PROTOCOLS, SSL_CIPHERS, get_ssl_cert_path

    cert_file, key_file = get_ssl_cert_path(domain)

    return f"""\
server {{
    listen 80;
    listen [::]:80;
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name {domain};

    ssl_certificate {cert_file};
    ssl_certificate_key {key_file};
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

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering on;
        proxy_intercept_errors off;
    }}
}}
"""


def _configure_nginx_proxy(domain: str, port: int) -> None:
    """Write an nginx site config and reload nginx."""
    from lib.nginx_config import generate_self_signed_cert

    generate_self_signed_cert(domain)

    domain_slug = domain.replace(".", "_").replace("-", "_")
    config_name = f"antistatic_{domain_slug}"
    config_file = f"/etc/nginx/sites-available/{config_name}"
    enabled_link = f"/etc/nginx/sites-enabled/{config_name}"

    run("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")

    config_content = generate_antistatic_nginx_config(domain, port)
    with open(config_file, "w", encoding="utf-8") as fh:
        fh.write(config_content)
    print(f"  ✓ Created nginx config: {config_file}")

    if not os.path.exists(enabled_link):
        run(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
        print(f"  ✓ Enabled nginx site: {config_name}")

    result = run("nginx -t", check=False)
    if result.returncode != 0:
        print("  ⚠ nginx configuration test failed")
    else:
        run("systemctl reload nginx")
        print("  ✓ nginx reloaded")


def setup_antistatic_server(config: SetupConfig) -> None:
    """Install and run the antistatic lobby server behind nginx."""
    if not config.antistatic_server:
        return

    domain, port = parse_antistatic_spec(config.antistatic_server)
    print(f"  Setting up antistatic server: {domain} → 127.0.0.1:{port}")

    from web.web_steps import install_nginx
    install_nginx(config)

    _ensure_antistatic_user()
    _download_antistatic_binary(_detect_arch())

    cleanup_service(ANTISTATIC_SERVICE)

    service_file = f"/etc/systemd/system/{ANTISTATIC_SERVICE}.service"
    with open(service_file, "w", encoding="utf-8") as fh:
        fh.write(generate_antistatic_service(port))

    run("systemctl daemon-reload")
    run(f"systemctl enable {ANTISTATIC_SERVICE}")
    run(f"systemctl restart {ANTISTATIC_SERVICE}")
    print(f"  ✓ Created and started systemd service: {ANTISTATIC_SERVICE}")

    if is_service_active(ANTISTATIC_SERVICE):
        print(f"  ✓ {ANTISTATIC_SERVICE} is running")
    else:
        print(
            f"  ⚠ Warning: {ANTISTATIC_SERVICE} may not be running. "
            f"Check with: systemctl status {ANTISTATIC_SERVICE}"
        )

    _configure_nginx_proxy(domain, port)
