#!/usr/bin/env python3
"""Manage infra_tools static HTTPS publications and loopback forwards."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import pwd
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from common.service_tools import godot_web_publish


POLICY_FILE = "/etc/infra-tools/internal-web/policy.json"
FORWARD_STATE_FILE = "/etc/infra-tools/internal-web/forwards.json"
FORWARD_NGINX_SITE = "/etc/nginx/sites-available/infra-tools-web-forwards"
FORWARD_NGINX_LINK = "/etc/nginx/sites-enabled/infra-tools-web-forwards"
GAMES_ROOT = "/srv/infra-tools/web/games"
_FORWARD_MARKER = "# Managed by infra_tools HTTPS forwarding"
_FORWARD_RULE_PREFIX = "infra_tools HTTPS forward"
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SAFE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9_./-]+$")
_UFW_NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.*)$")
_PROFILES = ("general", "godot")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the infra_tools HTTPS publishing gateway",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish", help="Publish static content")
    publish_commands = publish.add_subparsers(dest="publish_kind", required=True)
    godot = publish_commands.add_parser("godot", help="Export and publish a Godot game")
    godot.add_argument("game", nargs="?")
    godot.add_argument("project_positional", nargs="?")
    godot.add_argument("--project", dest="project_option")
    godot.add_argument("--preset", default="Web")
    godot.add_argument("--debug", action="store_true")
    godot.add_argument("--no-precompress", action="store_true")
    godot.add_argument("--json", action="store_true")
    godot.add_argument("--open", action="store_true")

    list_command = commands.add_parser("list", aliases=["ls"], help="List published games")
    list_command.add_argument("--json", action="store_true")

    url = commands.add_parser("url", help="Print a published game URL")
    url.add_argument("game")

    remove = commands.add_parser("remove", help="Remove a published game")
    remove.add_argument("game")
    remove.add_argument("--yes", action="store_true", help="Confirm permanent removal")

    doctor = commands.add_parser("doctor", help="Verify HTTPS and Godot headers")
    doctor.add_argument("name")
    doctor.add_argument("--json", action="store_true")

    ca = commands.add_parser("ca", help="Show the managed CA path and fingerprint")
    ca.add_argument("--json", action="store_true")

    forward = commands.add_parser("forward", help="Manage HTTPS loopback forwards")
    forward_commands = forward.add_subparsers(dest="forward_command", required=True)
    forward_add = forward_commands.add_parser("add", help="Add or update a forward")
    forward_add.add_argument("name")
    forward_add.add_argument(
        "--listen",
        default="auto",
        help="External HTTPS port or 'auto' (default: auto)",
    )
    forward_add.add_argument(
        "--to",
        required=True,
        metavar="LOOPBACK:PORT",
        help="Loopback HTTP upstream, such as 127.0.0.1:3000",
    )
    forward_add.add_argument("--profile", choices=_PROFILES, default="general")
    forward_add.add_argument("--json", action="store_true")
    forward_remove = forward_commands.add_parser("remove", help="Remove a forward")
    forward_remove.add_argument("name")
    forward_remove.add_argument("--json", action="store_true")
    forward_list = forward_commands.add_parser("list", aliases=["ls"], help="List forwards")
    forward_list.add_argument("--json", action="store_true")
    forward_reconcile = forward_commands.add_parser(
        "reconcile",
        help="Reconcile generated Nginx and UFW state",
    )
    forward_reconcile.add_argument("--json", action="store_true")
    return parser


def _validate_name(value: str, label: str = "name") -> str:
    if not _NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must use lowercase letters, digits, '-' or '_' and start "
            "with a letter or digit"
        )
    return value


def _validate_username(value: object) -> str:
    if not isinstance(value, str) or not _USERNAME_PATTERN.fullmatch(value):
        raise RuntimeError("Invalid internal-web username")
    return value


def _validate_managed_path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_PATH_PATTERN.fullmatch(value)
        or os.path.normpath(value) != value
    ):
        raise RuntimeError(f"Invalid {label} path in internal-web policy")
    return value


def _read_json(path: str, label: str) -> object:
    if os.path.islink(path):
        raise RuntimeError(f"Refusing symlinked {label}: {path}")
    try:
        with open(path, encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} is not configured") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read {label}") from exc


def _validate_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("Invalid base URL in internal-web policy")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise RuntimeError("Invalid base URL in internal-web policy")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError("Invalid base URL port in internal-web policy") from exc
    return value.rstrip("/")


def _load_policy() -> dict[str, object]:
    value = _read_json(POLICY_FILE, "internal-web policy")
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("Invalid internal-web policy")
    base_url = _validate_base_url(value.get("base_url"))
    cert_path = _validate_managed_path(value.get("certificate"), "certificate")
    key_path = _validate_managed_path(value.get("certificate_key"), "certificate key")
    raw_users = value.get("users")
    if not isinstance(raw_users, list) or not raw_users:
        raise RuntimeError("Internal-web policy has no users")
    users = list(dict.fromkeys(_validate_username(user) for user in raw_users))
    raw_sources = value.get("access_sources", [])
    if not isinstance(raw_sources, list):
        raise RuntimeError("Invalid access sources in internal-web policy")
    sources: list[str] = []
    for source in raw_sources:
        if not isinstance(source, str):
            raise RuntimeError("Invalid access source in internal-web policy")
        try:
            ipaddress.ip_network(source, strict=False)
        except ValueError as exc:
            raise RuntimeError("Invalid access source in internal-web policy") from exc
        sources.append(source)
    port_min = value.get("forward_port_min")
    port_max = value.get("forward_port_max")
    if (
        not isinstance(port_min, int)
        or isinstance(port_min, bool)
        or not isinstance(port_max, int)
        or isinstance(port_max, bool)
        or not 1024 <= port_min <= port_max <= 65535
    ):
        raise RuntimeError("Invalid forwarding range in internal-web policy")
    ca_certificate = value.get("ca_certificate")
    if ca_certificate is not None:
        ca_certificate = _validate_managed_path(ca_certificate, "CA certificate")
    return {
        "access_sources": list(dict.fromkeys(sources)),
        "base_url": base_url,
        "ca_certificate": ca_certificate,
        "certificate": cert_path,
        "certificate_key": key_path,
        "forward_port_max": port_max,
        "forward_port_min": port_min,
        "users": users,
        "version": 1,
    }


def _parse_upstream(value: str) -> tuple[str, int]:
    host = ""
    port_text = ""
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise ValueError("--to must be a loopback host and port")
        host = value[1:closing]
        port_text = value[closing + 2 :]
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            raise ValueError("--to must be a loopback host and port")
    try:
        address = ipaddress.ip_address(host)
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("--to must be a loopback host and port") from exc
    if not address.is_loopback or not 1024 <= port <= 65535:
        raise ValueError("--to must use loopback and an unprivileged port")
    return str(address), port


def _validate_route(value: object, policy: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError("Invalid HTTPS forward state")
    name = _validate_name(str(value.get("name", "")), "forward name")
    owner = _validate_username(value.get("owner"))
    if owner not in policy["users"]:
        raise RuntimeError("HTTPS forward owner is not allowed by policy")
    listen = value.get("listen")
    target_port = value.get("target_port")
    if (
        not isinstance(listen, int)
        or isinstance(listen, bool)
        or not policy["forward_port_min"] <= listen <= policy["forward_port_max"]
        or not isinstance(target_port, int)
        or isinstance(target_port, bool)
        or not 1024 <= target_port <= 65535
    ):
        raise RuntimeError("Invalid port in HTTPS forward state")
    target_host = value.get("target_host")
    try:
        address = ipaddress.ip_address(str(target_host))
    except ValueError as exc:
        raise RuntimeError("Invalid target in HTTPS forward state") from exc
    if not address.is_loopback:
        raise RuntimeError("HTTPS forward target is not loopback")
    profile = value.get("profile")
    if profile not in _PROFILES:
        raise RuntimeError("Invalid profile in HTTPS forward state")
    return {
        "listen": listen,
        "name": name,
        "owner": owner,
        "profile": profile,
        "target_host": str(address),
        "target_port": target_port,
    }


def _load_forwards(policy: dict[str, object]) -> list[dict[str, object]]:
    if not os.path.exists(FORWARD_STATE_FILE):
        return []
    value = _read_json(FORWARD_STATE_FILE, "HTTPS forward state")
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("Invalid HTTPS forward state")
    raw_routes = value.get("routes")
    if not isinstance(raw_routes, list):
        raise RuntimeError("Invalid HTTPS forward routes")
    routes = [_validate_route(route, policy) for route in raw_routes]
    names = [str(route["name"]) for route in routes]
    ports = [int(route["listen"]) for route in routes]
    if len(names) != len(set(names)) or len(ports) != len(set(ports)):
        raise RuntimeError("Duplicate HTTPS forward name or port")
    return sorted(routes, key=lambda route: (int(route["listen"]), str(route["name"])))


def _write_text_atomic(path: str, content: str, mode: int) -> None:
    if os.path.islink(path):
        raise RuntimeError(f"Refusing symlinked managed file: {path}")
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o755, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=parent,
        prefix=f".{os.path.basename(path)}-",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _write_forward_state(routes: list[dict[str, object]]) -> None:
    _write_text_atomic(
        FORWARD_STATE_FILE,
        json.dumps({"routes": routes, "version": 1}, indent=2, sort_keys=True) + "\n",
        0o644,
    )


def _forward_url(base_url: str, port: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    hostname = parsed.hostname or "localhost"
    url_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{url_host}:{port}/"


def render_forward_nginx(
    routes: list[dict[str, object]],
    policy: dict[str, object],
) -> str:
    """Render isolated TLS listeners for validated loopback forwards."""

    blocks = [_FORWARD_MARKER]
    for route in routes:
        target_host = str(route["target_host"])
        upstream_host = f"[{target_host}]" if ":" in target_host else target_host
        profile_headers = ""
        if route["profile"] == "godot":
            profile_headers = """
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Cross-Origin-Embedder-Policy "require-corp" always;"""
        blocks.append(
            f"""
# {route['name']} ({route['owner']}, {route['profile']})
server {{
    listen {route['listen']} ssl;
    listen [::]:{route['listen']} ssl;
    http2 on;
    server_name _;

    ssl_certificate {policy['certificate']};
    ssl_certificate_key {policy['certificate_key']};
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {{
        proxy_pass http://{upstream_host}:{route['target_port']};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;{profile_headers}
        add_header X-Content-Type-Options "nosniff" always;
        add_header Cache-Control "no-cache" always;
    }}
}}
""".rstrip()
        )
    return "\n".join(blocks) + "\n"


def _run_checked(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or label).strip()
        raise RuntimeError(f"{label}: {detail}")
    return result


def _ufw_rules() -> list[tuple[int, str, str]]:
    result = _run_checked(["ufw", "status", "numbered"], "Could not inspect UFW")
    rules: list[tuple[int, str, str]] = []
    for line in result.stdout.splitlines():
        match = _UFW_NUMBERED_RULE_RE.match(line.strip())
        if not match:
            continue
        comment = line.split("#", 1)[1].strip() if "#" in line else ""
        rules.append((int(match.group(1)), comment, line))
    return rules


def _desired_firewall_rules(
    routes: list[dict[str, object]],
    policy: dict[str, object],
) -> dict[str, list[str]]:
    desired: dict[str, list[str]] = {}
    sources = policy["access_sources"]
    for route in routes:
        port = int(route["listen"])
        name = str(route["name"])
        if sources:
            for source in sources:
                comment = f"{_FORWARD_RULE_PREFIX} {name} {port}/tcp source {source}"
                desired[comment] = [
                    "ufw",
                    "allow",
                    "from",
                    str(source),
                    "to",
                    "any",
                    "port",
                    str(port),
                    "proto",
                    "tcp",
                    "comment",
                    comment,
                ]
        else:
            comment = f"{_FORWARD_RULE_PREFIX} {name} {port}/tcp global"
            desired[comment] = ["ufw", "allow", f"{port}/tcp", "comment", comment]
    return desired


def _ufw_rule_matches_port(line: str, port: int) -> bool:
    return re.search(rf"(?<![0-9]){port}/tcp(?![0-9])", line) is not None


def _reconcile_firewall(
    routes: list[dict[str, object]],
    policy: dict[str, object],
) -> None:
    if shutil.which("ufw") is None:
        if not routes:
            return
        raise RuntimeError("HTTPS forwarding requires UFW")
    status = _run_checked(["ufw", "status"], "Could not inspect UFW status")
    if "Status: active" not in status.stdout:
        if not routes:
            return
        raise RuntimeError("HTTPS forwarding requires an active UFW firewall")
    existing = _ufw_rules()
    managed_comments = {
        comment for _number, comment, _line in existing if comment.startswith(_FORWARD_RULE_PREFIX)
    }
    for route in routes:
        listen_port = int(route["listen"])
        conflicts = [
            line
            for _number, comment, line in existing
            if _ufw_rule_matches_port(line, listen_port)
            and "ALLOW IN" in line
            and not comment.startswith(_FORWARD_RULE_PREFIX)
        ]
        if conflicts:
            raise RuntimeError(
                f"Unmanaged UFW rules already expose HTTPS forward port {route['listen']}"
            )

    desired = _desired_firewall_rules(routes, policy)
    for comment, command in desired.items():
        if comment not in managed_comments:
            _run_checked(command, f"Could not add UFW rule for {comment}")

    observed = _ufw_rules()
    observed_comments = {comment for _number, comment, _line in observed}
    missing = set(desired) - observed_comments
    if missing:
        raise RuntimeError("UFW did not retain requested HTTPS forward rules")
    stale_numbers = [
        number
        for number, comment, _line in observed
        if comment.startswith(_FORWARD_RULE_PREFIX) and comment not in desired
    ]
    for number in sorted(stale_numbers, reverse=True):
        _run_checked(
            ["ufw", "--force", "delete", str(number)],
            "Could not remove stale HTTPS forward firewall rule",
        )


def _ensure_forward_link() -> bool:
    if os.path.lexists(FORWARD_NGINX_LINK):
        if not (
            os.path.islink(FORWARD_NGINX_LINK)
            and os.path.realpath(FORWARD_NGINX_LINK) == FORWARD_NGINX_SITE
        ):
            raise RuntimeError("Refusing unmanaged HTTPS forward Nginx link")
        return False
    os.symlink(FORWARD_NGINX_SITE, FORWARD_NGINX_LINK)
    return True


def _restore_file(path: str, previous: str | None, mode: int) -> None:
    if previous is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    else:
        _write_text_atomic(path, previous, mode)


def _apply_forwards(
    routes: list[dict[str, object]],
    policy: dict[str, object],
) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Run HTTPS forward mutations with sudo")
    previous_site = None
    previous_state = None
    try:
        with open(FORWARD_NGINX_SITE, encoding="utf-8") as file_obj:
            previous_site = file_obj.read()
        if _FORWARD_MARKER not in previous_site:
            raise RuntimeError("Refusing unmanaged HTTPS forward Nginx site")
    except FileNotFoundError:
        pass
    try:
        with open(FORWARD_STATE_FILE, encoding="utf-8") as file_obj:
            previous_state = file_obj.read()
    except FileNotFoundError:
        pass

    link_created = False
    try:
        _write_text_atomic(FORWARD_NGINX_SITE, render_forward_nginx(routes, policy), 0o644)
        link_created = _ensure_forward_link()
        _run_checked(["nginx", "-t"], "Nginx rejected HTTPS forwarding")
        _reconcile_firewall(routes, policy)
        _write_forward_state(routes)
        _run_checked(["systemctl", "reload", "nginx"], "Could not reload Nginx")
    except Exception:
        _restore_file(FORWARD_NGINX_SITE, previous_site, 0o644)
        _restore_file(FORWARD_STATE_FILE, previous_state, 0o644)
        if link_created:
            try:
                os.unlink(FORWARD_NGINX_LINK)
            except FileNotFoundError:
                pass
        try:
            old_routes = _load_forwards(policy) if previous_state is not None else []
            _reconcile_firewall(old_routes, policy)
            _run_checked(["systemctl", "reload", "nginx"], "Could not restore Nginx")
        except Exception:
            pass
        raise


def _requesting_username(policy: dict[str, object]) -> str:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        username = _validate_username(sudo_user)
    else:
        username = _validate_username(pwd.getpwuid(os.getuid()).pw_name)
    if username not in policy["users"]:
        raise RuntimeError(f"User is not allowed to manage HTTPS forwards: {username}")
    return username


def _port_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def _select_listen_port(
    requested: str,
    routes: list[dict[str, object]],
    policy: dict[str, object],
    existing: dict[str, object] | None,
) -> int:
    used = {int(route["listen"]) for route in routes if route is not existing}
    if requested == "auto":
        if existing is not None:
            return int(existing["listen"])
        for port in range(int(policy["forward_port_min"]), int(policy["forward_port_max"]) + 1):
            if port not in used and _port_available(port):
                return port
        raise RuntimeError("No HTTPS forwarding port is available")
    try:
        port = int(requested)
    except ValueError as exc:
        raise ValueError("--listen must be 'auto' or an integer port") from exc
    if not policy["forward_port_min"] <= port <= policy["forward_port_max"]:
        raise ValueError(
            "--listen must be inside the managed forwarding range "
            f"{policy['forward_port_min']}-{policy['forward_port_max']}"
        )
    if port in used:
        raise ValueError(f"HTTPS port {port} is already assigned")
    if existing is None or port != existing["listen"]:
        if not _port_available(port):
            raise ValueError(f"HTTPS port {port} is already in use")
    return port


def _game_account() -> pwd.struct_passwd:
    account = pwd.getpwuid(os.getuid())
    if account.pw_uid == 0:
        raise RuntimeError("Run game commands as the configured non-root user")
    _validate_username(account.pw_name)
    return account


def _user_root(account: pwd.struct_passwd) -> str:
    root = os.path.join(GAMES_ROOT, account.pw_name)
    if os.path.islink(root) or not os.path.isdir(root):
        raise RuntimeError(f"Managed publishing directory is unavailable: {root}")
    if os.stat(root).st_uid != account.pw_uid:
        raise RuntimeError(f"Publishing directory is not owned by {account.pw_name}")
    return root


def _game_records(account: pwd.struct_passwd) -> list[dict[str, object]]:
    root = _user_root(account)
    records: list[dict[str, object]] = []
    for name in sorted(os.listdir(root)):
        if name.startswith(".") or name == godot_web_publish.CATALOG_FILE:
            continue
        path = os.path.join(root, name)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        metadata = godot_web_publish._metadata_for_game(path)
        records.append(
            {
                "debug": metadata.get("debug"),
                "game": name,
                "preset": metadata.get("preset"),
                "published_at": metadata.get("published_at"),
                "title": metadata.get("title") or name,
                "url": godot_web_publish._published_url(account.pw_name, name),
            }
        )
    return records


def _print_games(as_json: bool) -> int:
    records = _game_records(_game_account())
    if as_json:
        print(json.dumps({"games": records}, sort_keys=True))
    elif not records:
        print("No games published")
    else:
        for record in records:
            print(f"{record['game']}\t{record['url'] or '-'}")
    return 0


def _print_game_url(game: str) -> int:
    _validate_name(game, "game")
    account = _game_account()
    path = os.path.join(_user_root(account), game)
    if os.path.islink(path) or not os.path.isdir(path):
        raise RuntimeError(f"Published game does not exist: {game}")
    url = godot_web_publish._published_url(account.pw_name, game)
    if not url:
        raise RuntimeError("Internal-web base URL is unavailable")
    print(url)
    return 0


def _remove_game(game: str, confirmed: bool) -> int:
    _validate_name(game, "game")
    if not confirmed:
        raise ValueError("Removing a published game requires --yes")
    account = _game_account()
    root = _user_root(account)
    path = os.path.join(root, game)
    if os.path.islink(path) or not os.path.isdir(path):
        raise RuntimeError(f"Published game does not exist: {game}")
    if os.stat(path).st_uid != account.pw_uid:
        raise RuntimeError(f"Published game is not owned by {account.pw_name}: {game}")
    shutil.rmtree(path)
    godot_web_publish.write_user_catalog(root, account.pw_name)
    print(f"Removed published game {game}")
    return 0


def _https_headers(url: str) -> tuple[int, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"Range": "bytes=0-0", "User-Agent": "infra-web-doctor/1"},
    )
    try:
        with urllib.request.urlopen(
            request,
            context=ssl.create_default_context(),
            timeout=15,
        ) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"HTTPS request failed for {url}: {exc}") from exc


def _doctor(name: str, as_json: bool) -> int:
    _validate_name(name)
    account = _game_account()
    game_path = os.path.join(_user_root(account), name)
    profile = "general"
    wasm_url = None
    if os.path.isdir(game_path) and not os.path.islink(game_path):
        url = godot_web_publish._published_url(account.pw_name, name)
        if not url:
            raise RuntimeError("Internal-web base URL is unavailable")
        profile = "godot"
        for current_dir, _dirs, files in os.walk(game_path):
            wasm_name = next((file_name for file_name in files if file_name.endswith(".wasm")), None)
            if wasm_name:
                relative = os.path.relpath(os.path.join(current_dir, wasm_name), game_path)
                wasm_url = urllib.parse.urljoin(url, urllib.parse.quote(relative))
                break
    else:
        policy = _load_policy()
        routes = _load_forwards(policy)
        route = next((item for item in routes if item["name"] == name), None)
        if route is None:
            raise RuntimeError(f"No published game or HTTPS forward named {name}")
        if route["owner"] != account.pw_name:
            raise RuntimeError(f"HTTPS forward is owned by another user: {name}")
        url = _forward_url(str(policy["base_url"]), int(route["listen"]))
        profile = str(route["profile"])

    status, headers = _https_headers(url)
    errors: list[str] = []
    if status >= 400:
        errors.append(f"HTTPS endpoint returned {status}")
    if profile == "godot":
        if headers.get("cross-origin-opener-policy") != "same-origin":
            errors.append("missing Cross-Origin-Opener-Policy: same-origin")
        if headers.get("cross-origin-embedder-policy") != "require-corp":
            errors.append("missing Cross-Origin-Embedder-Policy: require-corp")
    wasm_headers: dict[str, str] = {}
    if wasm_url:
        wasm_status, wasm_headers = _https_headers(wasm_url)
        if wasm_status >= 400:
            errors.append(f"WASM endpoint returned {wasm_status}")
        content_type = wasm_headers.get("content-type", "").split(";", 1)[0]
        if content_type != "application/wasm":
            errors.append(f"WASM content type is {content_type or 'missing'}")
    result = {
        "errors": errors,
        "headers": headers,
        "name": name,
        "ok": not errors,
        "status": status,
        "url": url,
        "wasm_headers": wasm_headers,
    }
    if as_json:
        print(json.dumps(result, sort_keys=True))
    elif errors:
        print(f"{name}: failed ({'; '.join(errors)})")
    else:
        print(f"{name}: healthy ({url})")
    return 0 if not errors else 1


def _print_ca(as_json: bool) -> int:
    policy = _load_policy()
    path = policy.get("ca_certificate")
    if not isinstance(path, str) or not os.path.isfile(path):
        result = {"ca_certificate": None, "publicly_trusted": True}
    else:
        digest = hashlib.sha256()
        with open(path, "rb") as file_obj:
            while chunk := file_obj.read(1024 * 1024):
                digest.update(chunk)
        result = {
            "ca_certificate": path,
            "publicly_trusted": False,
            "sha256": digest.hexdigest(),
        }
    if as_json:
        print(json.dumps(result, sort_keys=True))
    elif result["publicly_trusted"]:
        print("The internal-web endpoint uses a publicly trusted certificate")
    else:
        print(f"{result['ca_certificate']}\nSHA-256 {result['sha256']}")
    return 0


def _forward_add(args: argparse.Namespace) -> int:
    name = _validate_name(args.name, "forward name")
    policy = _load_policy()
    owner = _requesting_username(policy)
    routes = _load_forwards(policy)
    existing = next((route for route in routes if route["name"] == name), None)
    if existing is not None and existing["owner"] != owner:
        raise RuntimeError(f"HTTPS forward is owned by another user: {name}")
    target_host, target_port = _parse_upstream(args.to)
    listen = _select_listen_port(args.listen, routes, policy, existing)
    route = {
        "listen": listen,
        "name": name,
        "owner": owner,
        "profile": args.profile,
        "target_host": target_host,
        "target_port": target_port,
    }
    updated = [item for item in routes if item["name"] != name]
    updated.append(route)
    updated.sort(key=lambda item: (int(item["listen"]), str(item["name"])))
    _apply_forwards(updated, policy)
    result = {**route, "url": _forward_url(str(policy["base_url"]), listen)}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"{name}: {result['url']} -> http://{target_host}:{target_port} "
            f"({args.profile})"
        )
    return 0


def _forward_remove(args: argparse.Namespace) -> int:
    name = _validate_name(args.name, "forward name")
    policy = _load_policy()
    owner = _requesting_username(policy)
    routes = _load_forwards(policy)
    existing = next((route for route in routes if route["name"] == name), None)
    if existing is None:
        raise RuntimeError(f"HTTPS forward does not exist: {name}")
    if existing["owner"] != owner:
        raise RuntimeError(f"HTTPS forward is owned by another user: {name}")
    _apply_forwards([route for route in routes if route["name"] != name], policy)
    if args.json:
        print(json.dumps({"name": name, "removed": True}, sort_keys=True))
    else:
        print(f"Removed HTTPS forward {name}")
    return 0


def _forward_list(as_json: bool) -> int:
    policy = _load_policy()
    account = pwd.getpwuid(os.getuid())
    username = account.pw_name
    routes = [
        {**route, "url": _forward_url(str(policy["base_url"]), int(route["listen"]))}
        for route in _load_forwards(policy)
        if os.geteuid() == 0 or route["owner"] == username
    ]
    if as_json:
        print(json.dumps({"forwards": routes}, sort_keys=True))
    elif not routes:
        print("No HTTPS forwards configured")
    else:
        for route in routes:
            print(
                f"{route['name']}\t{route['url']}\thttp://"
                f"{route['target_host']}:{route['target_port']}\t{route['profile']}"
            )
    return 0


def _forward_reconcile(as_json: bool) -> int:
    policy = _load_policy()
    routes = _load_forwards(policy)
    _apply_forwards(routes, policy)
    if as_json:
        print(json.dumps({"forwards": len(routes), "reconciled": True}, sort_keys=True))
    else:
        print(f"Reconciled {len(routes)} HTTPS forward(s)")
    return 0


def _publish_godot(args: argparse.Namespace) -> int:
    forwarded: list[str] = []
    if args.game:
        forwarded.append(args.game)
    if args.project_positional:
        forwarded.append(args.project_positional)
    if args.project_option:
        forwarded.extend(["--project", args.project_option])
    forwarded.extend(["--preset", args.preset])
    if args.debug:
        forwarded.append("--debug")
    if args.no_precompress:
        forwarded.append("--no-precompress")
    if args.json:
        forwarded.append("--json")
    if args.open:
        forwarded.append("--open")
    return godot_web_publish.main(forwarded)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "publish":
            return _publish_godot(args)
        if args.command in ("list", "ls"):
            return _print_games(args.json)
        if args.command == "url":
            return _print_game_url(args.game)
        if args.command == "remove":
            return _remove_game(args.game, args.yes)
        if args.command == "doctor":
            return _doctor(args.name, args.json)
        if args.command == "ca":
            return _print_ca(args.json)
        if args.command == "forward":
            if args.forward_command == "add":
                return _forward_add(args)
            if args.forward_command == "remove":
                return _forward_remove(args)
            if args.forward_command in ("list", "ls"):
                return _forward_list(args.json)
            if args.forward_command == "reconcile":
                return _forward_reconcile(args.json)
    except (OSError, RuntimeError, ValueError) as exc:
        as_json = bool(getattr(args, "json", False))
        if as_json:
            print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
