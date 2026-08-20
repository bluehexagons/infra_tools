"""Remote health reporting for infra-tools-managed Gogs services."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from typing import Any

from lib.cache import load_setup_command
from lib.ssh_utils import build_ssh_command
from lib.validators import validate_host, validate_username


DEFAULT_MIN_FREE_BYTES = 1024 * 1024 * 1024
DEFAULT_MIN_FREE_INODES = 10_000


def add_gogs_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Register Gogs operator commands."""
    parser = subparsers.add_parser("gogs", help="Inspect a managed Gogs service")
    commands = parser.add_subparsers(dest="gogs_command", help="Gogs command")
    health = commands.add_parser(
        "health",
        help="Check Gogs service, storage, SQLite, LFS, updates, and nginx",
    )
    health.add_argument("host", help="Remote Gogs host")
    health.add_argument("--username", "-u", help="SSH username")
    health.add_argument("--key", "-i", dest="ssh_key", help="SSH private key")
    health.add_argument("--json", action="store_true", help="Output stable JSON")
    health.add_argument(
        "--min-free-bytes",
        type=int,
        default=DEFAULT_MIN_FREE_BYTES,
        help="Fail below this many available bytes",
    )
    health.add_argument(
        "--min-free-inodes",
        type=int,
        default=DEFAULT_MIN_FREE_INODES,
        help="Fail below this many available inodes",
    )


def _resolve_connection(
    host: str,
    username: str | None,
    ssh_key: str | None,
) -> tuple[str, str | None]:
    config = load_setup_command(host)
    if config:
        username = username or config.username
        ssh_key = ssh_key or config.ssh_key
    return username or "root", ssh_key


def _remote_health_script(min_free_bytes: int, min_free_inodes: int) -> str:
    """Return a root-side Python health probe with no external dependencies."""
    return f'''
import configparser, glob, json, os, re, subprocess

STATE = "/opt/infra_tools/state/gogs.json"
MIN_FREE_BYTES = {min_free_bytes}
MIN_FREE_INODES = {min_free_inodes}

def run(*args):
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=60)

def directory_size(path):
    if not os.path.exists(path):
        return 0
    result = run("du", "-sx", "-B1", "--", path)
    try:
        return int(result.stdout.split()[0]) if result.returncode == 0 else None
    except (IndexError, ValueError):
        return None

with open(STATE, encoding="utf-8") as source:
    state = json.load(source)
data_path = state["data_path"]
config_path = state["config_path"]

service = run("systemctl", "is-active", "gogs")
service_active = service.returncode == 0 and service.stdout.strip() == "active"

mount = run("findmnt", "-J", "-o", "SOURCE,FSTYPE,TARGET", "-T", data_path)
mount_value = {{}}
if mount.returncode == 0:
    try:
        filesystems = json.loads(mount.stdout).get("filesystems", [])
        if filesystems:
            mount_value = filesystems[0]
    except (ValueError, TypeError):
        pass

stats = os.statvfs(data_path)
free_bytes = stats.f_bavail * stats.f_frsize
free_inodes = stats.f_favail
paths = [
    data_path,
    data_path + "/data",
    data_path + "/data/lfs-objects",
    data_path + "/data/tmp/lfs-objects",
    data_path + "/repositories",
    data_path + "/log",
]
path_health = {{}}
for path in paths:
    access = run("runuser", "-u", "git", "--", "test", "-r", path, "-a", "-w", path)
    path_health[path] = os.path.isdir(path) and access.returncode == 0

database_path = data_path + "/data/gogs.db"
database = run("sqlite3", database_path, "PRAGMA quick_check;")
sqlite_healthy = database.returncode == 0 and database.stdout.strip() == "ok"

usage = {{
    "repositories": directory_size(data_path + "/repositories"),
    "lfs_objects": directory_size(data_path + "/data/lfs-objects"),
    "attachments": directory_size(data_path + "/data/attachments"),
    "logs": directory_size(data_path + "/log"),
}}

update = run(
    "systemctl", "show", "auto-update-gogs.service",
    "--property=ActiveState,Result,ExecMainStatus", "--no-pager",
)
update_state = {{}}
for line in update.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        update_state[key] = value
update_failed = update_state.get("ActiveState") == "failed" or update_state.get("Result") not in (None, "", "success")
update_state["available"] = update.returncode == 0
timer = run(
    "systemctl", "show", "auto-update-gogs.timer",
    "--property=ActiveState,NextElapseUSecRealtime", "--no-pager",
)
timer_state = {{}}
for line in timer.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        timer_state[key] = value
timer_state["available"] = timer.returncode == 0
timer_active = timer_state.get("ActiveState") == "active"
timer_scheduled = timer_state.get("NextElapseUSecRealtime") not in (None, "", "n/a")

app = configparser.ConfigParser(interpolation=None)
app.read(config_path)
external_url = app.get("server", "EXTERNAL_URL", fallback="")
lfs_client_reachable = not bool(re.match(r"^https?://(?:127\\.0\\.0\\.1|localhost)(?::|/)", external_url))
nginx_required = external_url.startswith("https://")

nginx_limit_bytes = None
for nginx_path in glob.glob("/etc/nginx/sites-enabled/gogs_*"):
    try:
        content = open(nginx_path, encoding="utf-8").read()
    except OSError:
        continue
    match = re.search(r"client_max_body_size\\s+(\\d+)([kKmMgG]?)\\s*;", content)
    if match:
        scale = {{"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}}[match.group(2).lower()]
        nginx_limit_bytes = int(match.group(1)) * scale
        break

filesystem = str(mount_value.get("fstype", ""))
healthy = all((
    service_active,
    sqlite_healthy,
    all(path_health.values()),
    filesystem.lower() not in ("cifs", "smb3"),
    free_bytes >= MIN_FREE_BYTES,
    free_inodes >= MIN_FREE_INODES,
    not update_failed,
    update_state["available"],
    timer_active,
    timer_scheduled,
    (not nginx_required and nginx_limit_bytes is None) or (nginx_limit_bytes is not None and nginx_limit_bytes >= 512 * 1024 * 1024),
))

print(json.dumps({{
    "healthy": healthy,
    "service_active": service_active,
    "release": {{"tag": state.get("tag_name"), "archive_sha256": state.get("archive_sha256")}},
    "storage": {{
        "data_path": data_path,
        "source": mount_value.get("source"),
        "filesystem": mount_value.get("fstype"),
        "mount_target": mount_value.get("target"),
        "free_bytes": free_bytes,
        "free_inodes": free_inodes,
        "min_free_bytes": MIN_FREE_BYTES,
        "min_free_inodes": MIN_FREE_INODES,
        "paths_healthy": path_health,
        "usage_bytes": usage,
    }},
    "sqlite_healthy": sqlite_healthy,
    "update_job": {{"failed": update_failed, **update_state}},
    "update_timer": {{"active": timer_active, "scheduled": timer_scheduled, **timer_state}},
    "nginx_upload_limit_bytes": nginx_limit_bytes,
    "external_url": external_url,
    "lfs_client_reachable": lfs_client_reachable,
}}, sort_keys=True))
'''


def inspect_remote_gogs(
    host: str,
    username: str | None,
    ssh_key: str | None,
    min_free_bytes: int,
    min_free_inodes: int,
) -> dict[str, Any]:
    """Run the Gogs probe over SSH and return its JSON result."""
    if not validate_host(host):
        raise ValueError(f"Invalid Gogs host: {host}")
    if min_free_bytes < 0 or min_free_inodes < 0:
        raise ValueError("Gogs capacity thresholds must be non-negative")
    username, ssh_key = _resolve_connection(host, username, ssh_key)
    if not validate_username(username):
        raise ValueError(f"Invalid username: {username}")
    script = _remote_health_script(min_free_bytes, min_free_inodes)
    interpreter = f"python3 -c {shlex.quote(script)}"
    remote_command = interpreter if username == "root" else f"sudo -n {interpreter}"
    command = build_ssh_command(
        host,
        username,
        ssh_key,
        batch_mode=True,
        remote_command=remote_command,
    )
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "remote probe failed"
        raise RuntimeError(f"Gogs health check failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gogs health check returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Gogs health check returned an invalid result")
    return value


def _format_health(value: dict[str, Any], host: str) -> str:
    storage = value.get("storage", {})
    update = value.get("update_job", {})
    timer = value.get("update_timer", {})
    usage = storage.get("usage_bytes", {})
    lines = [
        f"Gogs health for {host}: {'healthy' if value.get('healthy') else 'UNHEALTHY'}",
        f"  Service: {'active' if value.get('service_active') else 'inactive'}",
        f"  SQLite: {'ok' if value.get('sqlite_healthy') else 'FAILED'}",
        f"  Storage: {storage.get('source')} ({storage.get('filesystem')}) at {storage.get('mount_target')}",
        f"  Free: {storage.get('free_bytes')} bytes, {storage.get('free_inodes')} inodes",
        "  Usage: " + ", ".join(f"{name}={size}" for name, size in usage.items()),
        f"  Update job: {'FAILED' if update.get('failed') else 'ok'}",
        f"  Update timer: {'active' if timer.get('active') and timer.get('scheduled') else 'FAILED'}",
        f"  Nginx upload limit: {value.get('nginx_upload_limit_bytes')}",
        f"  Remote LFS endpoint: {'reachable' if value.get('lfs_client_reachable') else 'loopback-only'}",
    ]
    return "\n".join(lines)


def run_gogs_command(args: argparse.Namespace) -> int:
    """Dispatch Gogs operator commands."""
    if args.gogs_command != "health":
        print("Error: Gogs command required", file=sys.stderr)
        return 1
    try:
        value = inspect_remote_gogs(
            args.host,
            args.username,
            args.ssh_key,
            args.min_free_bytes,
            args.min_free_inodes,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, indent=2, sort_keys=True) if args.json else _format_health(value, args.host))
    return 0 if value.get("healthy") is True else 1
