"""Setup steps for the antistatic lobby server.

Deploys the antistatic-server Go binary (https://github.com/bluehexagons/antistatic-server)
as a systemd service behind an nginx reverse proxy.
"""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import SetupConfig

from lib.release_management import (
    detect_release_arch,
    fetch_preferred_github_release_asset,
    load_json_state,
    write_json_state,
)
from lib.remote_utils import run, user_exists, is_service_active
from lib.systemd_service import cleanup_service


ANTISTATIC_USER = "antistatic"
ANTISTATIC_BINARY = "/usr/local/bin/antistatic-server"
ANTISTATIC_SERVICE = "antistatic"
ANTISTATIC_RELEASE_STATE_FILE = "/opt/infra_tools/state/antistatic_release.json"
GITHUB_REPO = "bluehexagons/antistatic-server"
DEFAULT_INTERNAL_PORT = 8080
DEFAULT_STUN_PORT = 3478
PROXY_LISTEN_HOST = "127.0.0.1"
TRUSTED_NGINX_PROXY_CIDRS = "127.0.0.1/32,::1/128"

ANTISTATIC_DB_USER = "antistatic-db"
ANTISTATIC_DB_BINARY = "/usr/local/bin/antistatic-db"
ANTISTATIC_DB_SERVICE = "antistatic-db"
ANTISTATIC_DB_RELEASE_STATE_FILE = "/opt/infra_tools/state/antistatic_db_release.json"
ANTISTATIC_DB_GITHUB_REPO = "bluehexagons/antistatic-db"
ANTISTATIC_DB_DATA_DIR = "/var/lib/antistatic-db"
ANTISTATIC_DB_PATH = f"{ANTISTATIC_DB_DATA_DIR}/antistatic.db"
DEFAULT_DB_INTERNAL_PORT = 8081
FirewallRule = tuple[int, str, str]


def parse_antistatic_spec(spec: str) -> tuple[str, int]:
    """Parse a 'DOMAIN[:port]' spec into (domain, port).

    The port defaults to DEFAULT_INTERNAL_PORT when omitted or non-numeric.
    """
    spec = spec.strip()
    if spec.isdigit():
        return "", int(spec)
    if ":" in spec:
        domain, _, raw_port = spec.rpartition(":")
        try:
            return domain.strip(), int(raw_port)
        except ValueError:
            return domain.strip(), DEFAULT_INTERNAL_PORT
    return spec.strip(), DEFAULT_INTERNAL_PORT


def parse_antistatic_db_spec(spec: str) -> tuple[str, int]:
    """Parse an antistatic-db 'DOMAIN[:port]' spec into (domain, port)."""
    spec = spec.strip()
    if spec.isdigit():
        return "", int(spec)
    if ":" in spec:
        domain, _, raw_port = spec.rpartition(":")
        try:
            return domain.strip(), int(raw_port)
        except ValueError:
            return domain.strip(), DEFAULT_DB_INTERNAL_PORT
    return spec.strip(), DEFAULT_DB_INTERNAL_PORT


def _detect_arch() -> str:
    """Return the GitHub release architecture suffix for this machine."""
    return detect_release_arch()


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


def _ensure_antistatic_db_user() -> None:
    """Create a dedicated antistatic-db system user if needed."""
    if user_exists(ANTISTATIC_DB_USER):
        print(f"  ✓ System user already exists: {ANTISTATIC_DB_USER}")
        return
    run(
        f"useradd --system --no-create-home --shell /usr/sbin/nologin "
        f"{ANTISTATIC_DB_USER}"
    )
    print(f"  ✓ Created system user: {ANTISTATIC_DB_USER}")


def _fetch_preferred_antistatic_release(arch: str) -> tuple[str, str]:
    """Return the preferred release tag and binary download URL for this architecture."""
    binary_name = f"antistatic-server-linux-{arch}"
    return fetch_preferred_github_release_asset(
        GITHUB_REPO,
        asset_matches=lambda _tag_name, asset_name: asset_name == binary_name,
        missing_asset_description=(
            f"No binary found for '{binary_name}' in the preferred releases of "
            f"https://github.com/{GITHUB_REPO}"
        ),
    )


def _fetch_preferred_antistatic_db_release(arch: str) -> tuple[str, str]:
    """Return the preferred antistatic-db release tag and binary URL."""
    binary_name = f"antistatic-db-linux-{arch}"
    return fetch_preferred_github_release_asset(
        ANTISTATIC_DB_GITHUB_REPO,
        asset_matches=lambda _tag_name, asset_name: asset_name == binary_name,
        missing_asset_description=(
            f"No binary found for '{binary_name}' in the preferred releases of "
            f"https://github.com/{ANTISTATIC_DB_GITHUB_REPO}"
        ),
    )


def _read_installed_antistatic_release() -> str | None:
    """Return the recorded antistatic release tag, if available."""
    if not os.path.exists(ANTISTATIC_RELEASE_STATE_FILE):
        return None
    release_state = load_json_state(
        ANTISTATIC_RELEASE_STATE_FILE,
        read_error_label="antistatic release metadata",
        invalid_state_message="Invalid antistatic release metadata, reinstalling preferred release",
    )
    tag_name = release_state.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        print("  ⚠ Warning: Missing antistatic release tag in metadata, reinstalling preferred release")
        return None
    return tag_name


def _write_installed_antistatic_release(tag_name: str) -> None:
    """Persist the installed antistatic release tag for future update checks."""
    write_json_state(ANTISTATIC_RELEASE_STATE_FILE, {"tag_name": tag_name})


def _read_installed_antistatic_db_release() -> str | None:
    """Return the recorded antistatic-db release tag, if available."""
    if not os.path.exists(ANTISTATIC_DB_RELEASE_STATE_FILE):
        return None
    release_state = load_json_state(
        ANTISTATIC_DB_RELEASE_STATE_FILE,
        read_error_label="antistatic-db release metadata",
        invalid_state_message="Invalid antistatic-db release metadata, reinstalling preferred release",
    )
    tag_name = release_state.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        print("  ⚠ Warning: Missing antistatic-db release tag in metadata, reinstalling preferred release")
        return None
    return tag_name


def _write_installed_antistatic_db_release(tag_name: str) -> None:
    """Persist the installed antistatic-db release tag for future update checks."""
    write_json_state(ANTISTATIC_DB_RELEASE_STATE_FILE, {"tag_name": tag_name})


def _download_antistatic_binary(arch: str) -> str:
    """Install the preferred antistatic-server release when needed.

    Returns the release tag that should be running after setup completes.
    """
    binary_name = f"antistatic-server-linux-{arch}"
    latest_tag, download_url = _fetch_preferred_antistatic_release(arch)
    installed_tag = _read_installed_antistatic_release()
    if installed_tag == latest_tag and os.path.exists(ANTISTATIC_BINARY):
        print(f"  ✓ antistatic-server already up to date ({latest_tag})")
        return latest_tag

    print(f"  Downloading {binary_name} ({latest_tag})...")
    tmp_path = f"/tmp/{binary_name}.{latest_tag}"
    run(
        f"curl -fL -o {shlex.quote(tmp_path)} {shlex.quote(download_url)}",
        check=True,
        display_cmd=f"curl -fL -o {tmp_path} <release URL>",
    )
    run(f"chmod +x {shlex.quote(tmp_path)}", check=True)
    run(f"mv {shlex.quote(tmp_path)} {ANTISTATIC_BINARY}", check=True)
    _write_installed_antistatic_release(latest_tag)
    print(f"  ✓ Installed {ANTISTATIC_BINARY} ({latest_tag})")
    return latest_tag


def _download_antistatic_db_binary(arch: str) -> str:
    """Install the preferred antistatic-db release when needed."""
    binary_name = f"antistatic-db-linux-{arch}"
    latest_tag, download_url = _fetch_preferred_antistatic_db_release(arch)
    installed_tag = _read_installed_antistatic_db_release()
    if installed_tag == latest_tag and os.path.exists(ANTISTATIC_DB_BINARY):
        print(f"  ✓ antistatic-db already up to date ({latest_tag})")
        return latest_tag

    print(f"  Downloading {binary_name} ({latest_tag})...")
    tmp_path = f"/tmp/{binary_name}.{latest_tag}"
    run(
        f"curl -fL -o {shlex.quote(tmp_path)} {shlex.quote(download_url)}",
        check=True,
        display_cmd=f"curl -fL -o {tmp_path} <release URL>",
    )
    run(f"chmod +x {shlex.quote(tmp_path)}", check=True)
    run(f"mv {shlex.quote(tmp_path)} {ANTISTATIC_DB_BINARY}", check=True)
    _write_installed_antistatic_db_release(latest_tag)
    print(f"  ✓ Installed {ANTISTATIC_DB_BINARY} ({latest_tag})")
    return latest_tag


def _antistatic_service_listen_options(domain: str) -> tuple[str, bool]:
    """Return (host, trust_proxy) for antistatic-server systemd execution."""
    if domain:
        return PROXY_LISTEN_HOST, True
    return "", False


def generate_antistatic_service(
    port: int,
    host: str = "",
    trust_proxy: bool = True,
    stun_port: int = DEFAULT_STUN_PORT,
) -> str:
    """Return systemd unit file content for the antistatic server."""
    host_args = f" -host {host}" if host else ""
    stun_args = f" -stun-port {stun_port}" if stun_port > 0 else ""
    proxy_args = (
        f" -trust-proxy -trusted-proxy-cidrs {TRUSTED_NGINX_PROXY_CIDRS}"
        if trust_proxy
        else ""
    )
    return f"""\
[Unit]
Description=Antistatic lobby server
Documentation=https://github.com/bluehexagons/antistatic-server
After=network.target
Wants=network.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User={ANTISTATIC_USER}
Group={ANTISTATIC_USER}
ExecStart={ANTISTATIC_BINARY}{host_args} -port {port}{stun_args}{proxy_args}
Restart=on-failure
RestartSec=5

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
"""


def generate_antistatic_db_service(port: int, host: str = "127.0.0.1") -> str:
    """Return systemd unit file content for antistatic-db."""
    host_args = f" -host {host}" if host else ""
    return f"""\
[Unit]
Description=Antistatic DB service
Documentation=https://github.com/bluehexagons/antistatic-db
After=network.target
Wants=network.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User={ANTISTATIC_DB_USER}
Group={ANTISTATIC_DB_USER}
StateDirectory=antistatic-db
WorkingDirectory={ANTISTATIC_DB_DATA_DIR}
ExecStart={ANTISTATIC_DB_BINARY}{host_args} -port {port} -db {ANTISTATIC_DB_PATH} -trust-proxy
Restart=on-failure
RestartSec=5

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
"""


def generate_antistatic_nginx_config(domain: str, port: int) -> str:
    """Return an nginx site config that proxies all traffic to the antistatic server."""
    if not domain:
        raise ValueError("Antistatic nginx config requires a non-empty domain")

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


def _remove_empty_domain_nginx_proxy() -> None:
    """Remove stale configs generated by the old ':PORT' hostless parser bug."""
    for path in (
        "/etc/nginx/sites-enabled/antistatic_",
        "/etc/nginx/sites-available/antistatic_",
    ):
        if os.path.lexists(path):
            os.remove(path)
            print(f"  ✓ Removed invalid nginx config: {path}")


def _maybe_configure_nginx_proxy(domain: str, port: int, service_name: str) -> None:
    if domain:
        _configure_nginx_proxy(domain, port)
        return

    _remove_empty_domain_nginx_proxy()
    print(
        f"  ✓ No hostname configured; skipping nginx proxy for {service_name} "
        f"(service listens directly on :{port})"
    )


def get_antistatic_public_firewall_rules(domain: str, port: int) -> tuple[FirewallRule, ...]:
    """Return required public firewall rules for antistatic-server."""
    rules: list[FirewallRule] = []
    if not domain:
        rules.append((port, "tcp", f"{ANTISTATIC_SERVICE} direct port"))
    rules.append((DEFAULT_STUN_PORT, "udp", f"{ANTISTATIC_SERVICE} STUN"))
    return tuple(rules)


def _maybe_configure_firewall_rules(rules: tuple[FirewallRule, ...], service_name: str) -> None:
    """Allow service firewall rules when UFW is already enforcing rules."""
    if not rules:
        return

    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode != 0:
        allowed_ports = ", ".join(f"{port}/{protocol}" for port, protocol, _ in rules)
        print(
            f"  ✓ Firewall inactive; no port rules needed for {service_name} "
            f"({allowed_ports})"
        )
        return

    for rule_port, protocol, comment in rules:
        result = run(
            f"ufw allow {rule_port}/{protocol} comment {shlex.quote(comment)}",
            check=False,
        )
        if result.returncode == 0:
            print(f"  ✓ Firewall allows {comment}: {rule_port}/{protocol}")
        else:
            print(f"  ⚠ Warning: Failed to allow {comment}: {rule_port}/{protocol}")


def _maybe_configure_direct_port_firewall(domain: str, port: int, service_name: str) -> None:
    """Allow the direct hostless service port when UFW is already enforcing rules."""
    if domain:
        return

    _maybe_configure_firewall_rules(
        ((port, "tcp", f"{service_name} direct port"),),
        service_name,
    )


def _maybe_configure_antistatic_firewall(domain: str, port: int) -> None:
    """Allow antistatic-server public ports when UFW is already enforcing rules."""
    _maybe_configure_firewall_rules(
        get_antistatic_public_firewall_rules(domain, port),
        ANTISTATIC_SERVICE,
    )


def setup_antistatic_server(config: SetupConfig) -> None:
    """Install and run the antistatic lobby server behind nginx."""
    if not config.antistatic_server:
        return

    domain, port = parse_antistatic_spec(config.antistatic_server)
    service_host, trust_proxy = _antistatic_service_listen_options(domain)
    listen_label = f"{domain} → 127.0.0.1:{port}" if domain else f":{port}"
    print(f"  Setting up antistatic server: {listen_label}")

    from web.web_steps import install_nginx
    install_nginx(config)

    _ensure_antistatic_user()
    _download_antistatic_binary(_detect_arch())

    cleanup_service(ANTISTATIC_SERVICE)

    service_file = f"/etc/systemd/system/{ANTISTATIC_SERVICE}.service"
    with open(service_file, "w", encoding="utf-8") as fh:
        fh.write(
            generate_antistatic_service(
                port,
                host=service_host,
                trust_proxy=trust_proxy,
            )
        )

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

    _maybe_configure_nginx_proxy(domain, port, ANTISTATIC_SERVICE)
    _maybe_configure_antistatic_firewall(domain, port)
    if config.enable_cloudflare:
        print(
            "  ℹ Cloudflare tunnels do not proxy UDP; antistatic still needs "
            f"direct IP reachability on {DEFAULT_STUN_PORT}/udp"
        )


def setup_antistatic_db(config: SetupConfig) -> None:
    """Install and run antistatic-db behind nginx from GitHub releases."""
    if not config.antistatic_db:
        return

    domain, port = parse_antistatic_db_spec(config.antistatic_db)
    db_host = "127.0.0.1" if domain else ""
    listen_label = f"{domain} → 127.0.0.1:{port}" if domain else f":{port}"
    print(f"  Setting up antistatic-db: {listen_label}")

    from web.web_steps import install_nginx
    install_nginx(config)

    _ensure_antistatic_db_user()
    _download_antistatic_db_binary(_detect_arch())

    cleanup_service(ANTISTATIC_DB_SERVICE)

    service_file = f"/etc/systemd/system/{ANTISTATIC_DB_SERVICE}.service"
    with open(service_file, "w", encoding="utf-8") as fh:
        fh.write(generate_antistatic_db_service(port, host=db_host))

    run("systemctl daemon-reload")
    run(f"systemctl enable {ANTISTATIC_DB_SERVICE}")
    run(f"systemctl restart {ANTISTATIC_DB_SERVICE}")
    print(f"  ✓ Created and started systemd service: {ANTISTATIC_DB_SERVICE}")

    if is_service_active(ANTISTATIC_DB_SERVICE):
        print(f"  ✓ {ANTISTATIC_DB_SERVICE} is running")
    else:
        print(
            f"  ⚠ Warning: {ANTISTATIC_DB_SERVICE} may not be running. "
            f"Check with: systemctl status {ANTISTATIC_DB_SERVICE}"
        )

    _maybe_configure_nginx_proxy(domain, port, ANTISTATIC_DB_SERVICE)
    _maybe_configure_direct_port_firewall(domain, port, ANTISTATIC_DB_SERVICE)
