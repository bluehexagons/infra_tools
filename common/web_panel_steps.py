"""Install the optional authenticated infra-tools web panel."""

from __future__ import annotations

import os
import pwd
import shutil
import tempfile
import time
from typing import Any

from lib.atomic_io import write_json_atomic, write_text_atomic
from lib.auth_failure_bans import (
    configure_nginx_auth_failure_ban,
    remove_nginx_auth_failure_ban,
)
from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, is_service_active, run
from lib.validation import validate_filesystem_path
from lib.validators import validate_username


WEB_PANEL_SERVICE_NAME = "infra-tools-web-panel"
WEB_PANEL_SERVICE_FILE = f"/etc/systemd/system/{WEB_PANEL_SERVICE_NAME}.service"
WEB_PANEL_CONFIG_DIR = "/etc/infra-tools/web-panel"
WEB_PANEL_MANIFEST = f"{WEB_PANEL_CONFIG_DIR}/config.json"
WEB_PANEL_AUTH_FILE = f"{WEB_PANEL_CONFIG_DIR}/htpasswd"
WEB_PANEL_PAYLOAD_FILE = "/opt/infra_tools/web_panel_payload/htpasswd"
WEB_PANEL_SOCKET = "/run/infra-tools-web-panel/http.sock"
WEB_PANEL_SCRIPT = "/opt/infra_tools/common/service_tools/web_panel_service.py"
WEB_PANEL_NGINX_SITE = "/etc/nginx/sites-available/infra-tools-web-panel"
WEB_PANEL_NGINX_LINK = "/etc/nginx/sites-enabled/infra-tools-web-panel"
WEB_PANEL_AUTH_FAILURE_LOG = "/var/log/nginx/infra-tools-web-panel-auth-failures.log"
_NGINX_MARKER = "# Managed by infra_tools web panel"
_SERVICE_MARKER = "# Managed by infra_tools web panel"


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def web_panel_url(config: SetupConfig) -> str | None:
    """Return the externally useful web panel URL for summaries."""

    if config.web_panel_port is None:
        return None
    scheme = "https" if config.enable_ssl else "http"
    default_port = 443 if scheme == "https" else 80
    suffix = "" if config.web_panel_port == default_port else f":{config.web_panel_port}"
    return f"{scheme}://{_url_host(config.host)}{suffix}/"


def _split_service_spec(spec: str, default_port: int) -> tuple[str, int]:
    normalized = spec.strip()
    if normalized.isdigit():
        return "", int(normalized)
    if ":" not in normalized:
        return normalized, default_port
    domain, separator, raw_port = normalized.rpartition(":")
    if separator and raw_port.isdigit():
        return domain, int(raw_port)
    return normalized, default_port


def _http_url(host: str, port: int | None, scheme: str) -> str:
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port is None or port == default_port else f":{port}"
    return f"{scheme}://{_url_host(host)}{suffix}/"


def _preferred_host(config: SetupConfig, identities: list[str]) -> str:
    if config.system_hostname:
        return config.system_hostname
    return next(
        (
            identity
            for identity in identities
            if identity not in {"localhost", "127.0.0.1", "::1"}
        ),
        identities[0],
    )


def build_web_panel_manifest(
    config: SetupConfig,
    identities: list[str],
) -> dict[str, Any]:
    """Build non-secret configured service and access metadata."""

    host = _preferred_host(config, identities)
    services: list[dict[str, str]] = []
    access: list[dict[str, str]] = [
        {
            "label": "SSH",
            "value": f"ssh {config.username}@{host}",
            "description": "Shell and file transfer",
        }
    ]

    if config.system_type == "server_web" and not (
        config.web_panel_port == 80 and not config.enable_ssl
    ):
        services.append(
            {
                "label": "Web server",
                "url": _http_url(host, None, "http"),
                "description": "Default Nginx site",
            }
        )

    if config.gogs:
        domain, port = _split_service_spec(str(config.gogs[0]), 3000)
        if domain or config.effective_gogs_sources():
            scheme = "https" if config.enable_ssl or config.enable_cloudflare else "http"
            public_port = None if config.enable_cloudflare and domain else port
            services.append(
                {
                    "label": "Gogs",
                    "url": _http_url(domain or host, public_port, scheme),
                    "description": "Git repositories",
                }
            )

    for label, spec, default_port, description in (
        ("Antistatic lobby", config.antistatic_server, 8080, "Game lobby"),
        ("Antistatic DB", config.antistatic_db, 8081, "Game database"),
    ):
        if not spec:
            continue
        domain, port = _split_service_spec(spec, default_port)
        scheme = (
            "https"
            if domain and (config.enable_ssl or config.enable_cloudflare)
            else "http"
        )
        services.append(
            {
                "label": label,
                "url": _http_url(domain or host, None if domain else port, scheme),
                "description": description,
            }
        )

    if config.enable_rdp:
        access.append(
            {
                "label": "Remote desktop",
                "value": f"{_url_host(host)}:3389",
                "description": "RDP client connection",
            }
        )
    if config.enable_samba:
        access.append(
            {
                "label": "Samba / SMB",
                "value": f"//{_url_host(host)}",
                "description": "Authenticated file shares",
            }
        )
        for share in config.samba_shares or []:
            if len(share) >= 2:
                access.append(
                    {
                        "label": f"SMB share: {share[1]}_{share[0]}",
                        "value": f"smb://{_url_host(host)}/{share[1]}_{share[0]}",
                        "description": str(share[2]) if len(share) >= 3 else "",
                    }
                )

    title = config.friendly_name or config.system_hostname or _preferred_host(
        config, identities
    )
    return {
        "version": 1,
        "title": title,
        "host": host,
        "system_type": config.system_type,
        "username": config.username,
        "services": services,
        "access": access,
        "features": {
            "t3_update": "t3code" in (config.web_interfaces or []),
            "t3_github_readiness": config.github_auth_payload,
            "t3_git_identity_readiness": config.git_identity_payload,
        },
    }


def render_web_panel_nginx(
    identities: list[str],
    port: int,
    *,
    cert_path: str | None = None,
    key_path: str | None = None,
) -> str:
    """Render the Basic-Auth reverse proxy for the Unix-socket app."""

    ssl = cert_path is not None and key_path is not None
    listen_options = " ssl" if ssl else ""
    tls = ""
    if ssl:
        tls = f"""
    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:infra_tools_web_panel:10m;
    ssl_session_timeout 1d;
"""
    server_names = " ".join(_url_host(identity) for identity in identities)
    return f"""{_NGINX_MARKER}
limit_req_zone $binary_remote_addr zone=infra_tools_web_panel_auth:10m rate=120r/m;

map $status $infra_tools_web_panel_auth_failure {{
    default 0;
    401 1;
}}

log_format infra_tools_web_panel_auth '$remote_addr [$time_local] infra-tools-auth-failure';

server {{
    listen {port}{listen_options};
    listen [::]:{port}{listen_options};
    server_name {server_names};
{tls}
    access_log {WEB_PANEL_AUTH_FAILURE_LOG} infra_tools_web_panel_auth
        if=$infra_tools_web_panel_auth_failure;
    auth_basic "infra-tools web panel";
    auth_basic_user_file {WEB_PANEL_AUTH_FILE};
    client_max_body_size 16k;

    location / {{
        limit_req zone=infra_tools_web_panel_auth burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://unix:{WEB_PANEL_SOCKET}:/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 35s;
        proxy_send_timeout 35s;
    }}
}}
"""


def _validate_htpasswd_file(
    path: str,
    expected_username: str | None = None,
) -> None:
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError(f"Web panel auth must be a regular file: {path}")
    if not 0 < os.path.getsize(path) <= 64 * 1024:
        raise RuntimeError("Web panel auth file is empty or too large")
    try:
        with open(path, encoding="utf-8") as file_obj:
            records = [line.rstrip("\n") for line in file_obj if line.rstrip("\n")]
    except UnicodeDecodeError as exc:
        raise RuntimeError("Web panel auth file must be UTF-8 text") from exc
    if not records:
        raise RuntimeError("Web panel auth file has no user records")
    usernames: list[str] = []
    for record in records:
        username, separator, password_hash = record.partition(":")
        if (
            not separator
            or not validate_username(username)
            or not password_hash.startswith("$")
            or any(ord(character) < 32 or ord(character) == 127 for character in record)
        ):
            raise RuntimeError("Web panel auth file contains an invalid record")
        usernames.append(username)
    if expected_username is not None and usernames != [expected_username]:
        raise RuntimeError(
            "Web panel auth must contain exactly the setup username; "
            "supply --web-panel-password to replace it"
        )


def _replace_auth_file(payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".htpasswd-", dir=WEB_PANEL_CONFIG_DIR)
    try:
        with os.fdopen(descriptor, "wb") as file_obj:
            file_obj.write(payload)
        os.chmod(temporary, 0o640)
        os.replace(temporary, WEB_PANEL_AUTH_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _install_auth_file(expected_username: str) -> tuple[bool, bytes | None]:
    validate_filesystem_path(WEB_PANEL_CONFIG_DIR, must_exist=False)
    if os.path.lexists(WEB_PANEL_CONFIG_DIR) and (
        os.path.islink(WEB_PANEL_CONFIG_DIR)
        or not os.path.isdir(WEB_PANEL_CONFIG_DIR)
    ):
        raise RuntimeError(f"Refusing unsafe web panel config path: {WEB_PANEL_CONFIG_DIR}")
    os.makedirs(WEB_PANEL_CONFIG_DIR, mode=0o750, exist_ok=True)
    existing = None
    if os.path.lexists(WEB_PANEL_AUTH_FILE):
        _validate_htpasswd_file(WEB_PANEL_AUTH_FILE)
        with open(WEB_PANEL_AUTH_FILE, "rb") as file_obj:
            existing = file_obj.read()
    if os.path.lexists(WEB_PANEL_PAYLOAD_FILE):
        _validate_htpasswd_file(WEB_PANEL_PAYLOAD_FILE, expected_username)
        with open(WEB_PANEL_PAYLOAD_FILE, "rb") as file_obj:
            desired = file_obj.read()
        if existing != desired:
            _replace_auth_file(desired)
            changed = True
        else:
            changed = False
    elif existing is None:
        raise RuntimeError(
            "The web panel needs --web-panel-password on first setup"
        )
    else:
        _validate_htpasswd_file(WEB_PANEL_AUTH_FILE, expected_username)
        changed = False
    web_account = pwd.getpwnam("www-data")
    os.chown(WEB_PANEL_CONFIG_DIR, 0, web_account.pw_gid)
    os.chmod(WEB_PANEL_CONFIG_DIR, 0o750)
    os.chown(WEB_PANEL_AUTH_FILE, 0, web_account.pw_gid)
    os.chmod(WEB_PANEL_AUTH_FILE, 0o640)
    return changed, existing


def _restore_auth_file(previous: bytes | None) -> None:
    """Restore credentials after a later panel configuration failure."""

    if previous is None:
        try:
            os.unlink(WEB_PANEL_AUTH_FILE)
        except FileNotFoundError:
            return
    else:
        _replace_auth_file(previous)
        web_account = pwd.getpwnam("www-data")
        os.chown(WEB_PANEL_AUTH_FILE, 0, web_account.pw_gid)
        os.chmod(WEB_PANEL_AUTH_FILE, 0o640)
    if shutil.which("nginx"):
        run("systemctl reload nginx", check=False)


def _ensure_nginx() -> None:
    if not install_package("nginx", "nginx", "apt-get install -y -qq nginx"):
        raise RuntimeError("Failed to install Nginx for the web panel")
    if not is_service_active("nginx"):
        run("systemctl enable --now nginx", check=True)


def _restore_nginx_site(previous: str | None, link_created: bool) -> None:
    if previous is None:
        try:
            os.unlink(WEB_PANEL_NGINX_SITE)
        except FileNotFoundError:
            pass
    else:
        write_text_atomic(WEB_PANEL_NGINX_SITE, previous, mode=0o644)
    if link_created:
        try:
            os.unlink(WEB_PANEL_NGINX_LINK)
        except FileNotFoundError:
            pass


def _write_nginx_site(content: str) -> bool:
    previous = None
    if os.path.lexists(WEB_PANEL_NGINX_SITE):
        if os.path.islink(WEB_PANEL_NGINX_SITE) or not os.path.isfile(WEB_PANEL_NGINX_SITE):
            raise RuntimeError(f"Refusing unmanaged web panel Nginx site: {WEB_PANEL_NGINX_SITE}")
        with open(WEB_PANEL_NGINX_SITE, encoding="utf-8") as file_obj:
            previous = file_obj.read()
        if _NGINX_MARKER not in previous:
            raise RuntimeError(f"Refusing unmanaged web panel Nginx site: {WEB_PANEL_NGINX_SITE}")
    changed = previous != content
    if changed:
        write_text_atomic(WEB_PANEL_NGINX_SITE, content, mode=0o644)
    link_created = False
    if os.path.lexists(WEB_PANEL_NGINX_LINK):
        if not (
            os.path.islink(WEB_PANEL_NGINX_LINK)
            and os.path.realpath(WEB_PANEL_NGINX_LINK) == WEB_PANEL_NGINX_SITE
            and previous is not None
        ):
            raise RuntimeError(f"Refusing unmanaged web panel Nginx link: {WEB_PANEL_NGINX_LINK}")
    else:
        os.symlink(WEB_PANEL_NGINX_SITE, WEB_PANEL_NGINX_LINK)
        changed = True
        link_created = True
    try:
        validation = run("nginx -t", check=False, capture_output=True)
    except Exception:
        _restore_nginx_site(previous, link_created)
        raise
    if validation.returncode != 0:
        _restore_nginx_site(previous, link_created)
        raise RuntimeError("Nginx rejected the web panel configuration")
    if changed:
        try:
            run("systemctl reload nginx", check=True)
        except Exception:
            _restore_nginx_site(previous, link_created)
            try:
                rollback_validation = run(
                    "nginx -t", check=False, capture_output=True
                )
                if rollback_validation.returncode == 0:
                    run("systemctl reload nginx", check=False)
            except Exception:
                pass
            raise
    return changed


def _systemd_quote(value: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Systemd value contains control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_managed_service(content: str) -> bool:
    return _SERVICE_MARKER in content or (
        "Description=infra-tools web panel" in content
        and f"ExecStart=/usr/bin/python3 {WEB_PANEL_SCRIPT} " in content
    )


def _restore_service(previous: str | None) -> None:
    if previous is None:
        run(
            f"systemctl disable --now {WEB_PANEL_SERVICE_NAME}.service",
            check=False,
        )
        try:
            os.unlink(WEB_PANEL_SERVICE_FILE)
        except FileNotFoundError:
            pass
    else:
        write_text_atomic(WEB_PANEL_SERVICE_FILE, previous, mode=0o644)
    run("systemctl daemon-reload", check=False)
    if previous is not None:
        run(
            f"systemctl restart {WEB_PANEL_SERVICE_NAME}.service",
            check=False,
        )


def _configure_service(config: SetupConfig, home: str) -> bool:
    service_user = config.username if config.username != "root" else "nobody"
    service_home = home if service_user == config.username else "/nonexistent"
    content = f"""{_SERVICE_MARKER}
[Unit]
Description=infra-tools web panel
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
User={service_user}
Group=www-data
RuntimeDirectory=infra-tools-web-panel
RuntimeDirectoryMode=0750
UMask=0007
Environment={_systemd_quote('HOME=' + service_home)}
Environment=XDG_RUNTIME_DIR=/run/user/{pwd.getpwnam(service_user).pw_uid}
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{pwd.getpwnam(service_user).pw_uid}/bus
ExecStart=/usr/bin/python3 {WEB_PANEL_SCRIPT} --config {WEB_PANEL_MANIFEST} --socket {WEB_PANEL_SOCKET}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectSystem=full
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictSUIDSGID=true
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    previous = None
    if os.path.lexists(WEB_PANEL_SERVICE_FILE) and (
        os.path.islink(WEB_PANEL_SERVICE_FILE)
        or not os.path.isfile(WEB_PANEL_SERVICE_FILE)
    ):
        raise RuntimeError(
            f"Refusing unmanaged web panel service: {WEB_PANEL_SERVICE_FILE}"
        )
    try:
        with open(WEB_PANEL_SERVICE_FILE, encoding="utf-8") as file_obj:
            previous = file_obj.read()
    except OSError:
        pass
    if previous is not None and not _is_managed_service(previous):
        raise RuntimeError(
            f"Refusing unmanaged web panel service: {WEB_PANEL_SERVICE_FILE}"
        )
    changed = previous != content
    try:
        if changed:
            write_text_atomic(WEB_PANEL_SERVICE_FILE, content, mode=0o644)
            run("systemctl daemon-reload", check=True)
        run(f"systemctl enable {WEB_PANEL_SERVICE_NAME}.service", check=True)
        # The service reads its manifest only at startup, so restart even when
        # the unit itself is unchanged.
        run(f"systemctl restart {WEB_PANEL_SERVICE_NAME}.service", check=True)
        for _attempt in range(25):
            if os.path.exists(WEB_PANEL_SOCKET) and is_service_active(
                WEB_PANEL_SERVICE_NAME
            ):
                return changed
            time.sleep(0.2)
        status = run(
            f"systemctl status {WEB_PANEL_SERVICE_NAME}.service "
            "--no-pager --lines=20",
            check=False,
            capture_output=True,
        )
        detail = (
            getattr(status, "stderr", "") or getattr(status, "stdout", "")
        ).strip()
        message = "The web panel service did not create its HTTP socket"
        raise RuntimeError(message + (f":\n{detail}" if detail else ""))
    except Exception:
        if changed:
            _restore_service(previous)
        raise


def _preflight_web_panel_removal() -> tuple[str | None, bool]:
    if os.path.lexists(WEB_PANEL_SERVICE_FILE):
        if os.path.islink(WEB_PANEL_SERVICE_FILE) or not os.path.isfile(
            WEB_PANEL_SERVICE_FILE
        ):
            raise RuntimeError(
                f"Refusing unmanaged web panel service: {WEB_PANEL_SERVICE_FILE}"
            )
        with open(WEB_PANEL_SERVICE_FILE, encoding="utf-8") as file_obj:
            service_content = file_obj.read()
        if not _is_managed_service(service_content):
            raise RuntimeError(
                f"Refusing unmanaged web panel service: {WEB_PANEL_SERVICE_FILE}"
            )

    nginx_content = None
    if os.path.lexists(WEB_PANEL_NGINX_SITE):
        if os.path.islink(WEB_PANEL_NGINX_SITE) or not os.path.isfile(
            WEB_PANEL_NGINX_SITE
        ):
            raise RuntimeError(
                f"Refusing unmanaged web panel Nginx site: {WEB_PANEL_NGINX_SITE}"
            )
        with open(WEB_PANEL_NGINX_SITE, encoding="utf-8") as file_obj:
            nginx_content = file_obj.read()
        if _NGINX_MARKER not in nginx_content:
            raise RuntimeError(
                f"Refusing unmanaged web panel Nginx site: {WEB_PANEL_NGINX_SITE}"
            )

    link_exists = os.path.lexists(WEB_PANEL_NGINX_LINK)
    if link_exists and not (
        nginx_content is not None
        and os.path.islink(WEB_PANEL_NGINX_LINK)
        and os.path.realpath(WEB_PANEL_NGINX_LINK) == WEB_PANEL_NGINX_SITE
    ):
        raise RuntimeError(
            f"Refusing unmanaged web panel Nginx link: {WEB_PANEL_NGINX_LINK}"
        )

    if os.path.lexists(WEB_PANEL_CONFIG_DIR) and (
        os.path.islink(WEB_PANEL_CONFIG_DIR)
        or not os.path.isdir(WEB_PANEL_CONFIG_DIR)
    ):
        raise RuntimeError(
            f"Refusing unsafe web panel config path: {WEB_PANEL_CONFIG_DIR}"
        )
    for path in (WEB_PANEL_MANIFEST, WEB_PANEL_AUTH_FILE):
        if os.path.lexists(path) and (
            os.path.islink(path) or not os.path.isfile(path)
        ):
            raise RuntimeError(f"Refusing unsafe web panel file: {path}")
    return nginx_content, link_exists


def _remove_nginx_site(nginx_content: str | None, link_exists: bool) -> None:
    if nginx_content is None and not link_exists:
        return
    if link_exists:
        os.unlink(WEB_PANEL_NGINX_LINK)
    if nginx_content is not None:
        os.unlink(WEB_PANEL_NGINX_SITE)
    if not shutil.which("nginx"):
        return
    try:
        validation = run("nginx -t", check=False, capture_output=True)
        if validation.returncode != 0:
            raise RuntimeError("Nginx is invalid after removing the web panel")
        run("systemctl reload nginx", check=True)
    except Exception:
        if nginx_content is not None:
            write_text_atomic(WEB_PANEL_NGINX_SITE, nginx_content, mode=0o644)
        if link_exists and not os.path.lexists(WEB_PANEL_NGINX_LINK):
            os.symlink(WEB_PANEL_NGINX_SITE, WEB_PANEL_NGINX_LINK)
        try:
            rollback_validation = run("nginx -t", check=False, capture_output=True)
            if rollback_validation.returncode == 0:
                run("systemctl reload nginx", check=False)
        except Exception:
            pass
        raise


def remove_web_panel() -> None:
    """Remove the panel, authentication data, and public Nginx listener."""

    nginx_content, link_exists = _preflight_web_panel_removal()
    _remove_nginx_site(nginx_content, link_exists)
    if os.path.exists(WEB_PANEL_SERVICE_FILE):
        run(f"systemctl disable --now {WEB_PANEL_SERVICE_NAME}.service", check=False)
        os.remove(WEB_PANEL_SERVICE_FILE)
        run("systemctl daemon-reload", check=True)
    if os.path.lexists(WEB_PANEL_CONFIG_DIR):
        for name in ("config.json", "htpasswd"):
            path = os.path.join(WEB_PANEL_CONFIG_DIR, name)
            if os.path.lexists(path):
                os.remove(path)
        try:
            os.rmdir(WEB_PANEL_CONFIG_DIR)
        except OSError:
            pass
    remove_nginx_auth_failure_ban("web-panel")
    print("  ✓ Web panel removed")


def configure_web_panel(config: SetupConfig) -> None:
    """Install, update, or remove the optional web panel."""

    if is_dry_run():
        action = "remove" if config.disable_web_panel else "configure"
        print(f"  [DRY-RUN] Would {action} the web panel")
        return
    if config.disable_web_panel:
        remove_web_panel()
        return
    if config.web_panel_port is None:
        return

    from common.godot_web_steps import (
        configure_internal_web_host,
        discover_local_web_identities,
        identities_for_config,
        validate_web_identities,
    )

    _ensure_nginx()
    discovered = discover_local_web_identities()
    identities = validate_web_identities(
        [*identities_for_config(config.host, config.system_hostname), *discovered]
    )
    cert_path = None
    key_path = None
    if config.enable_ssl:
        _base_url, _local_ca, cert_path, key_path, _changed = configure_internal_web_host(
            identities,
            [config.username],
            config.effective_access_sources(),
            configure_static_site=True,
            install_utility=True,
        )

    auth_changed, previous_auth = _install_auth_file(config.username)
    try:
        manifest = build_web_panel_manifest(config, identities)
        os.makedirs(WEB_PANEL_CONFIG_DIR, mode=0o750, exist_ok=True)
        write_json_atomic(WEB_PANEL_MANIFEST, manifest, mode=0o644, sort_keys=True)
        account = (
            pwd.getpwnam(config.username)
            if config.username != "root"
            else pwd.getpwnam("nobody")
        )
        _configure_service(config, account.pw_dir)
        nginx_changed = _write_nginx_site(
            render_web_panel_nginx(
                identities,
                config.web_panel_port,
                cert_path=cert_path,
                key_path=key_path,
            )
        )
    except Exception:
        if auth_changed:
            _restore_auth_file(previous_auth)
        raise
    if auth_changed and not nginx_changed:
        run("systemctl reload nginx", check=True)
    configure_nginx_auth_failure_ban("web-panel", WEB_PANEL_AUTH_FAILURE_LOG)
    scheme = "https" if config.enable_ssl else "http"
    host = _preferred_host(config, identities)
    print(
        "  ✓ Web panel: "
        + _http_url(host, config.web_panel_port, scheme)
    )
    if not config.enable_ssl:
        print("  ⚠ Web panel Basic Auth uses plaintext HTTP; add --ssl for encrypted login")


__all__ = [
    "build_web_panel_manifest",
    "configure_web_panel",
    "web_panel_url",
    "remove_web_panel",
    "render_web_panel_nginx",
]
