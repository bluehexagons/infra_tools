"""Setup steps for Gogs."""

from __future__ import annotations

import os
import secrets
import shlex
import tempfile
from typing import Any, Mapping

from lib.atomic_io import write_json_atomic, write_text_atomic
from lib.config import SetupConfig
from lib.nginx_config import SSL_CIPHERS, SSL_PROTOCOLS, generate_self_signed_cert, get_ssl_cert_path
from lib.release_management import (
    detect_release_arch,
    fetch_preferred_github_release_asset,
    load_json_state,
    validate_release_download_url,
    validate_release_tag,
    write_json_state,
)
from lib.remote_utils import generate_password, is_service_active, run, user_exists
from lib.systemd_service import cleanup_service
from web.cloudflare_steps import run_cloudflare_tunnel_setup
from web.ssl_steps import install_certbot, obtain_letsencrypt_certificate, setup_certificate_renewal
from web.web_steps import install_nginx


GOGS_SERVICE = "gogs"
GOGS_GIT_USER = "git"
GOGS_GIT_GROUP = "git"
GOGS_INSTALL_ROOT = "/opt/gogs"
GOGS_RELEASES_DIR = f"{GOGS_INSTALL_ROOT}/releases"
GOGS_CURRENT_DIR = f"{GOGS_INSTALL_ROOT}/current"
GOGS_BINARY_LINK = "/usr/local/bin/gogs"
GOGS_STATE_FILE = "/opt/infra_tools/state/gogs.json"
GOGS_SECRET_KEY_FILE = "/opt/infra_tools/state/gogs_secret_key"
GOGS_ADMIN_CREDENTIALS_FILE = "/opt/infra_tools/state/gogs_admin_credentials.json"
GOGS_GITHUB_REPO = "gogs/gogs"
GOGS_SSH_DROPIN_DIR = "/etc/ssh/sshd_config.d"
GOGS_SSH_DROPIN_FILE = f"{GOGS_SSH_DROPIN_DIR}/99-gogs-git-user.conf"
DEFAULT_GOGS_HTTP_PORT = 3000
DEFAULT_GOGS_DATA_PATH = "/var/lib/gogs"


def parse_gogs_spec(spec: str, *, strict: bool = False) -> tuple[str, int]:
    """Parse a Gogs 'DOMAIN[:port]' spec into (domain, port)."""
    normalized = spec.strip()
    if not normalized:
        raise ValueError("Gogs target spec must be a non-empty string")

    if normalized.isdigit():
        port = int(normalized)
        if strict and not 1 <= port <= 65535:
            raise ValueError(f"Invalid Gogs port: {normalized}")
        return "", port if 1 <= port <= 65535 else DEFAULT_GOGS_HTTP_PORT

    if ":" not in normalized:
        return normalized, DEFAULT_GOGS_HTTP_PORT

    domain, _, raw_port = normalized.rpartition(":")
    domain = domain.strip()
    raw_port = raw_port.strip()
    if not raw_port:
        return domain, DEFAULT_GOGS_HTTP_PORT

    try:
        port = int(raw_port)
    except ValueError as exc:
        if strict:
            raise ValueError(f"Invalid Gogs port: {raw_port}") from exc
        return domain, DEFAULT_GOGS_HTTP_PORT

    if strict and not 1 <= port <= 65535:
        raise ValueError(f"Invalid Gogs port: {raw_port}")
    if not 1 <= port <= 65535:
        return domain, DEFAULT_GOGS_HTTP_PORT
    return domain, port


def _gogs_data_path(config: SetupConfig) -> str:
    if config.gogs and len(config.gogs) >= 2:
        return str(config.gogs[1])
    return DEFAULT_GOGS_DATA_PATH


def _gogs_public_host(config: SetupConfig, domain: str) -> str:
    return domain or config.host


def _gogs_external_url(config: SetupConfig, domain: str, port: int) -> str:
    scheme = "https" if domain and (config.enable_ssl or config.enable_cloudflare) else "http"
    host = _gogs_public_host(config, domain)
    if domain:
        return f"{scheme}://{host}/"
    default_port = 443 if scheme == "https" else 80
    port_suffix = f":{port}" if port != default_port else ""
    return f"{scheme}://{host}{port_suffix}/"


def _get_git_home() -> str:
    result = run(f"getent passwd {shlex.quote(GOGS_GIT_USER)}", check=False, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        return f"/home/{GOGS_GIT_USER}"

    fields = result.stdout.strip().split(":")
    if len(fields) < 6 or not fields[5]:
        return f"/home/{GOGS_GIT_USER}"
    return fields[5]


def _load_gogs_state() -> dict[str, Any]:
    return load_json_state(
        GOGS_STATE_FILE,
        read_error_label="Gogs state file",
        invalid_state_message="Invalid Gogs state file contents",
    )


def write_gogs_state(tag_name: str, data_path: str, config_path: str) -> None:
    write_json_state(
        GOGS_STATE_FILE,
        {
            "tag_name": tag_name,
            "data_path": data_path,
            "config_path": config_path,
        },
        mode=0o600,
    )


def read_installed_gogs_release() -> str | None:
    """Return the recorded installed Gogs release tag."""
    tag_name = _load_gogs_state().get("tag_name")
    return tag_name if isinstance(tag_name, str) and tag_name else None


def read_gogs_state() -> Mapping[str, Any]:
    """Return persisted Gogs install metadata."""
    return _load_gogs_state()


def fetch_preferred_gogs_release(arch: str) -> tuple[str, str]:
    """Return the preferred Gogs release tag and download URL for this architecture."""
    binary_name_suffix = f"_linux_{arch}.tar.gz"
    return fetch_preferred_github_release_asset(
        GOGS_GITHUB_REPO,
        asset_matches=lambda tag_name, asset_name: (
            asset_name.startswith(f"gogs_{tag_name}") and asset_name.endswith(binary_name_suffix)
        ),
        missing_asset_description=f"No Gogs Linux release asset found for architecture '{arch}'",
    )


def install_or_update_gogs_release() -> tuple[str, bool]:
    """Install the preferred Gogs release and return (tag, changed)."""
    arch = detect_release_arch()
    tag_name, download_url = fetch_preferred_gogs_release(arch)
    tag_name = validate_release_tag(tag_name)
    download_url = validate_release_download_url(download_url)
    release_dir = f"{GOGS_RELEASES_DIR}/{tag_name}"
    installed_tag = read_installed_gogs_release()
    current_binary = f"{GOGS_CURRENT_DIR}/gogs"
    if installed_tag == tag_name and os.path.exists(current_binary):
        print(f"  ✓ Gogs already up to date ({tag_name})")
        return tag_name, False

    run(f"mkdir -p {shlex.quote(GOGS_RELEASES_DIR)}")
    with tempfile.TemporaryDirectory(prefix="infra-tools-gogs-release-") as temporary_dir:
        archive_path = os.path.join(temporary_dir, "gogs.tar.gz")
        extract_dir = os.path.join(temporary_dir, "extract")
        run(
            "curl -fL --proto '=https' --proto-redir '=https' "
            f"-o {shlex.quote(archive_path)} {shlex.quote(download_url)}",
            check=True,
            display_cmd=(
                "curl -fL --proto '=https' --proto-redir '=https' "
                f"-o {archive_path} <release URL>"
            ),
        )
        run(f"mkdir -p {shlex.quote(extract_dir)}")
        run(f"rm -rf {shlex.quote(release_dir)}", check=False)
        run(
            f"tar -xzf {shlex.quote(archive_path)} -C {shlex.quote(extract_dir)}",
            check=True,
        )
        run(f"mv {shlex.quote(extract_dir)}/gogs {shlex.quote(release_dir)}", check=True)
        release_binary = f"{release_dir}/gogs"
        run(f"test -x {shlex.quote(release_binary)}", check=True)
        run(
            f"runuser -u {shlex.quote(GOGS_GIT_USER)} -- "
            f"{shlex.quote(release_binary)} --version",
            check=True,
            capture_output=True,
        )
        run(
            f"ln -sfn {shlex.quote(release_dir)} {shlex.quote(GOGS_CURRENT_DIR)}",
            check=True,
        )
        run(
            f"ln -sfn {shlex.quote(GOGS_CURRENT_DIR)}/gogs "
            f"{shlex.quote(GOGS_BINARY_LINK)}",
            check=True,
        )
    print(f"  ✓ Installed Gogs {tag_name}")
    return tag_name, True


def _ensure_git_user() -> str:
    git_home = _get_git_home()
    if not user_exists(GOGS_GIT_USER):
        run(
            f"useradd --create-home --home-dir {shlex.quote(git_home)} "
            f"--shell /usr/bin/git-shell {shlex.quote(GOGS_GIT_USER)}"
        )
        print(f"  ✓ Created system user: {GOGS_GIT_USER}")
    else:
        run(f"usermod -d {shlex.quote(git_home)} {shlex.quote(GOGS_GIT_USER)}", check=False)
        run(f"usermod -s /usr/bin/git-shell {shlex.quote(GOGS_GIT_USER)}", check=False)
        print(f"  ✓ Using existing system user: {GOGS_GIT_USER}")

    ssh_dir = f"{git_home}/.ssh"
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"touch {shlex.quote(ssh_dir)}/authorized_keys")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(ssh_dir)}/authorized_keys")
    run(f"chown -R {shlex.quote(GOGS_GIT_USER)}:{shlex.quote(GOGS_GIT_GROUP)} {shlex.quote(git_home)}")
    run(f"passwd -l {shlex.quote(GOGS_GIT_USER)}", check=False)
    return git_home


def _ensure_gogs_dependencies() -> None:
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq git git-lfs openssh-server sqlite3 curl ca-certificates", check=False)


def _reject_symlinked_gogs_path(path: str) -> None:
    """Reject symlinks in a managed Gogs data path before writing."""

    current = os.path.sep
    for component in os.path.abspath(path).split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise RuntimeError(f"Refusing symlinked Gogs data path: {current}")


def _ensure_gogs_data_dirs(data_path: str) -> str:
    config_dir = f"{data_path}/custom/conf"
    for path in (
        data_path,
        f"{data_path}/custom",
        config_dir,
        f"{data_path}/data",
        f"{data_path}/data/lfs-objects",
        f"{data_path}/data/tmp/lfs-objects",
        f"{data_path}/repositories",
        f"{data_path}/log",
    ):
        _reject_symlinked_gogs_path(path)
        run(f"mkdir -p {shlex.quote(path)}")
    run(f"chown -R {shlex.quote(GOGS_GIT_USER)}:{shlex.quote(GOGS_GIT_GROUP)} {shlex.quote(data_path)}")
    return f"{config_dir}/app.ini"


def _load_or_create_gogs_secret_key() -> str:
    try:
        with open(GOGS_SECRET_KEY_FILE, "r", encoding="utf-8") as file_obj:
            value = file_obj.read().strip()
    except FileNotFoundError:
        value = ""
    if value:
        return value

    value = secrets.token_hex(32)
    write_text_atomic(GOGS_SECRET_KEY_FILE, f"{value}\n")
    return value


def generate_gogs_app_ini(
    config: SetupConfig,
    *,
    git_home: str,
    data_path: str,
    domain: str,
    port: int,
) -> str:
    """Return app.ini contents for a minimal self-hosted Gogs service."""
    public_host = _gogs_public_host(config, domain)
    external_url = _gogs_external_url(config, domain, port)
    http_addr = "127.0.0.1" if domain else "0.0.0.0"
    secret_key = _load_or_create_gogs_secret_key()
    return f"""APP_NAME = Gogs
RUN_USER = {GOGS_GIT_USER}
RUN_MODE = prod

[server]
EXTERNAL_URL = {external_url}
DOMAIN = {public_host}
PROTOCOL = http
HTTP_ADDR = {http_addr}
HTTP_PORT = {port}
LOCAL_ROOT_URL = http://127.0.0.1:{port}/
APP_DATA_PATH = {data_path}/data
DISABLE_SSH = false
SSH_DOMAIN = {public_host}
SSH_PORT = 22
SSH_ROOT_PATH = {git_home}/.ssh
REWRITE_AUTHORIZED_KEYS_AT_START = true
START_SSH_SERVER = false
SSH_KEYGEN_PATH = /usr/bin/ssh-keygen
OFFLINE_MODE = false
DISABLE_ROUTER_LOG = true

[repository]
ROOT = {data_path}/repositories
DISABLE_HTTP_GIT = false

[database]
TYPE = sqlite3
PATH = {data_path}/data/gogs.db

[lfs]
STORAGE = local
OBJECTS_PATH = {data_path}/data/lfs-objects
OBJECTS_TEMP_PATH = {data_path}/data/tmp/lfs-objects

[security]
INSTALL_LOCK = true
SECRET_KEY = {secret_key}

[auth]
DISABLE_REGISTRATION = true
ENABLE_REGISTRATION_CAPTCHA = false
"""


def generate_gogs_service(config_path: str) -> str:
    """Return a hardened systemd unit file for Gogs."""
    return f"""[Unit]
Description=Gogs
After=network.target ssh.service sshd.service
Wants=network.target

[Service]
Type=simple
User={GOGS_GIT_USER}
Group={GOGS_GIT_GROUP}
WorkingDirectory={GOGS_CURRENT_DIR}
ExecStart={GOGS_CURRENT_DIR}/gogs web --config {config_path}
Restart=always
RestartSec=2s
Environment=USER={GOGS_GIT_USER}
Environment=HOME={_get_git_home()}
ProtectSystem=full
PrivateDevices=yes
PrivateTmp=yes
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"""


def generate_gogs_nginx_config(
    domain: str,
    port: int,
    *,
    forwarded_proto: str,
) -> str:
    """Return an nginx site config that proxies to Gogs."""
    cert_file, key_file = get_ssl_cert_path(domain)
    return f"""server {{
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
    client_max_body_size 512m;

    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto {forwarded_proto};
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 300s;
    }}
}}
"""


def _write_gogs_nginx_config(config: SetupConfig, domain: str, port: int) -> None:
    generate_self_signed_cert(domain)
    config_name = f"gogs_{domain.replace('.', '_').replace('-', '_')}"
    config_file = f"/etc/nginx/sites-available/{config_name}"
    enabled_link = f"/etc/nginx/sites-enabled/{config_name}"
    forwarded_proto = "https" if config.enable_cloudflare else "$scheme"
    run("mkdir -p /var/www/letsencrypt/.well-known/acme-challenge")
    with open(config_file, "w", encoding="utf-8") as file_obj:
        file_obj.write(generate_gogs_nginx_config(domain, port, forwarded_proto=forwarded_proto))
    if not os.path.exists(enabled_link):
        run(f"ln -s {shlex.quote(config_file)} {shlex.quote(enabled_link)}")
    result = run("nginx -t", check=False)
    if result.returncode == 0:
        run("systemctl reload nginx")
        print("  ✓ nginx configured for Gogs")
    else:
        print("  ⚠ nginx configuration test failed")

    if config.enable_ssl:
        install_certbot(config)
        if obtain_letsencrypt_certificate([domain], config.ssl_email, domain):
            with open(config_file, "w", encoding="utf-8") as file_obj:
                file_obj.write(generate_gogs_nginx_config(domain, port, forwarded_proto=forwarded_proto))
            setup_certificate_renewal()
            result = run("nginx -t", check=False)
            if result.returncode == 0:
                run("systemctl reload nginx")
                print("  ✓ Let's Encrypt enabled for Gogs")

    if config.enable_cloudflare:
        run_cloudflare_tunnel_setup(config)


def _configure_git_ssh_access() -> None:
    os.makedirs(GOGS_SSH_DROPIN_DIR, exist_ok=True)
    with open(GOGS_SSH_DROPIN_FILE, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            f"""# Managed by infra_tools for Gogs Git-over-SSH
Match User {GOGS_GIT_USER}
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    PermitTTY no
    X11Forwarding no
    AllowTcpForwarding no
    PermitTunnel no
    GatewayPorts no
"""
        )

    reload_result = run("systemctl reload ssh", check=False)
    if reload_result.returncode != 0:
        run("systemctl reload sshd", check=False)
    print("  ✓ SSH configured for Git-over-SSH access")


def _maybe_configure_firewall(config: SetupConfig, domain: str, port: int) -> None:
    result = run("ufw status 2>/dev/null | grep -q 'Status: active'", check=False)
    if result.returncode != 0:
        return

    if domain:
        if config.enable_cloudflare:
            print("  ✓ Cloudflare tunnel enabled; not exposing public HTTP/HTTPS ports for Gogs")
            return
        for rule_port in (80, 443):
            run(f"ufw allow {rule_port}/tcp comment 'gogs web'", check=False)
        print("  ✓ Firewall allows Gogs web access on 80/tcp and 443/tcp")
        return

    run(f"ufw allow {port}/tcp comment 'gogs direct HTTP'", check=False)
    print(f"  ✓ Firewall allows direct Gogs access on {port}/tcp")


def build_gogs_admin_command(args: list[str], config_path: str) -> str:
    """Return a shell-safe command string for running the Gogs CLI as the git user."""
    git_home = _get_git_home()
    command = [
        "runuser",
        "-u",
        GOGS_GIT_USER,
        "--",
        "env",
        f"HOME={git_home}",
        GOGS_BINARY_LINK,
        "--config",
        config_path,
    ] + args
    return shlex.join(command)


def _redacted_admin_create_user_command(config_path: str, username: str, email: str) -> str:
    return build_gogs_admin_command(
        [
            "admin",
            "create-user",
            "--name",
            username,
            "--password",
            "[REDACTED]",
            "--email",
            email,
            "--admin",
        ],
        config_path,
    )


def _gogs_admin_user_exists(config_path: str, username: str, data_path: str) -> bool:
    database_path = f"{data_path}/data/gogs.db"
    if not os.path.exists(database_path):
        return False
    escaped_username = username.replace("'", "''")
    query = (
        "SELECT COUNT(*) FROM user "
        f"WHERE lower(name) = lower('{escaped_username}');"
    )
    result = run(
        f"sqlite3 {shlex.quote(database_path)} {shlex.quote(query)}",
        check=False,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "1"


def _write_admin_credentials(username: str, password: str) -> None:
    write_json_atomic(
        GOGS_ADMIN_CREDENTIALS_FILE,
        {"username": username, "password": password},
        mode=0o600,
        sort_keys=True,
    )


def _ensure_gogs_admin_account(config: SetupConfig, config_path: str, data_path: str) -> None:
    admin_username = config.username
    if _gogs_admin_user_exists(config_path, admin_username, data_path):
        print(f"  ✓ Gogs admin user already exists: {admin_username}")
        return

    password = generate_password(24)
    email = f"{admin_username}@localhost"
    result = run(
        build_gogs_admin_command(
            [
                "admin",
                "create-user",
                "--name",
                admin_username,
                "--password",
                password,
                "--email",
                email,
                "--admin",
            ],
            config_path,
        ),
        check=False,
        display_cmd=_redacted_admin_create_user_command(config_path, admin_username, email),
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to create initial Gogs admin account")

    _write_admin_credentials(admin_username, password)
    print(f"  ✓ Created initial Gogs admin user: {admin_username}")
    print(f"  ✓ Admin credentials saved to {GOGS_ADMIN_CREDENTIALS_FILE}")


def _run_gogs_post_setup_commands(config_path: str) -> None:
    for args, label in (
        (["admin", "rewrite-authorized-keys"], "authorized_keys"),
        (["admin", "resync-hooks"], "repository hooks"),
    ):
        result = run(build_gogs_admin_command(args, config_path), check=False)
        if result.returncode == 0:
            print(f"  ✓ Refreshed Gogs {label}")
        else:
            print(f"  ⚠ Failed to refresh Gogs {label}")


def setup_gogs(config: SetupConfig) -> None:
    """Install and run Gogs with HTTP(S) and Git-over-SSH enabled."""
    if not config.gogs:
        return

    domain, port = parse_gogs_spec(str(config.gogs[0]), strict=True)
    data_path = _gogs_data_path(config)
    listen_label = f"{domain} -> 127.0.0.1:{port}" if domain else f":{port}"
    print(f"  Setting up Gogs: {listen_label}")

    from common.storage_steps import assert_declared_storage_mount

    assert_declared_storage_mount(config, data_path)

    _ensure_gogs_dependencies()
    git_home = _ensure_git_user()
    config_path = _ensure_gogs_data_dirs(data_path)
    tag_name, _changed = install_or_update_gogs_release()
    with open(config_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            generate_gogs_app_ini(
                config,
                git_home=git_home,
                data_path=data_path,
                domain=domain,
                port=port,
            )
        )
    run(f"chown {shlex.quote(GOGS_GIT_USER)}:{shlex.quote(GOGS_GIT_GROUP)} {shlex.quote(config_path)}")
    write_gogs_state(tag_name, data_path, config_path)
    _configure_git_ssh_access()

    if domain:
        install_nginx(config)
        _write_gogs_nginx_config(config, domain, port)

    cleanup_service(GOGS_SERVICE)
    service_file = f"/etc/systemd/system/{GOGS_SERVICE}.service"
    with open(service_file, "w", encoding="utf-8") as file_obj:
        file_obj.write(generate_gogs_service(config_path))

    run("systemctl daemon-reload")
    run(f"systemctl enable {GOGS_SERVICE}")
    run(f"systemctl restart {GOGS_SERVICE}")
    print(f"  ✓ Created and started systemd service: {GOGS_SERVICE}")

    if is_service_active(GOGS_SERVICE):
        print(f"  ✓ {GOGS_SERVICE} is running")
    else:
        raise RuntimeError("Gogs service failed to start")

    _ensure_gogs_admin_account(config, config_path, data_path)
    _run_gogs_post_setup_commands(config_path)
    _maybe_configure_firewall(config, domain, port)
