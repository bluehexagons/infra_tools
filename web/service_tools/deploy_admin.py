#!/usr/bin/env python3
"""Narrow privileged operations used by the remote deployment account."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile


NGINX_AVAILABLE_DIR = "/etc/nginx/sites-available"
NGINX_ENABLED_DIR = "/etc/nginx/sites-enabled"
NGINX_BINARY = "/usr/sbin/nginx"
SYSTEMCTL_BINARY = "/bin/systemctl"
STAGED_CONFIG_PREFIX = "/tmp/infra-tools-nginx-"
MAX_NGINX_CONFIG_BYTES = 1024 * 1024

_CONFIG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,253}$")
_SERVICE_NAME_PATTERN = re.compile(r"^node-[a-z0-9][a-z0-9_.-]{0,126}$")


def validate_config_name(value: str) -> str:
    """Validate a name used below nginx's sites directories."""

    if not _CONFIG_NAME_PATTERN.fullmatch(value):
        raise ValueError("invalid nginx configuration name")
    return value


def validate_service_name(value: str) -> str:
    """Limit service management to generated Node units."""

    base_name = value[:-8] if value.endswith(".service") else value
    if base_name.endswith(".service") or not _SERVICE_NAME_PATTERN.fullmatch(base_name):
        raise ValueError("invalid deploy service name")
    return f"{base_name}.service"


def _run_checked(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(detail)


def _read_regular_file(path: str, max_bytes: int) -> tuple[bytes, int, int]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"path is not a regular file: {path}")
        if file_stat.st_size > max_bytes:
            raise ValueError(f"file exceeds {max_bytes} bytes: {path}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise ValueError(f"file exceeds {max_bytes} bytes: {path}")
        return content, stat.S_IMODE(file_stat.st_mode), file_stat.st_uid
    finally:
        os.close(fd)


def _atomic_write(path: str, content: bytes, mode: int = 0o644) -> None:
    fd, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}-", dir=os.path.dirname(path))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as file_obj:
            fd = -1
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _replace_symlink(path: str, target: str) -> None:
    temp_path = f"{path}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        os.symlink(target, temp_path)
        os.replace(temp_path, path)
    finally:
        if os.path.lexists(temp_path):
            os.unlink(temp_path)


def _capture_nginx_paths(config_name: str) -> tuple[bytes | None, int, str | None]:
    available_path = os.path.join(NGINX_AVAILABLE_DIR, config_name)
    enabled_path = os.path.join(NGINX_ENABLED_DIR, config_name)

    previous_content: bytes | None = None
    previous_mode = 0o644
    if os.path.lexists(available_path):
        previous_content, previous_mode, _owner = _read_regular_file(
            available_path,
            MAX_NGINX_CONFIG_BYTES,
        )

    previous_link: str | None = None
    if os.path.lexists(enabled_path):
        if not os.path.islink(enabled_path):
            raise ValueError(f"enabled nginx path is not a symlink: {enabled_path}")
        previous_link = os.readlink(enabled_path)

    return previous_content, previous_mode, previous_link


def _restore_nginx_paths(
    config_name: str,
    previous_content: bytes | None,
    previous_mode: int,
    previous_link: str | None,
) -> None:
    available_path = os.path.join(NGINX_AVAILABLE_DIR, config_name)
    enabled_path = os.path.join(NGINX_ENABLED_DIR, config_name)

    if previous_content is None:
        if os.path.lexists(available_path):
            os.unlink(available_path)
    else:
        _atomic_write(available_path, previous_content, previous_mode)

    if previous_link is None:
        if os.path.lexists(enabled_path):
            os.unlink(enabled_path)
    else:
        _replace_symlink(enabled_path, previous_link)


def install_nginx_config(config_name: str) -> None:
    """Install a staged deploy-owned nginx site and validate the full config."""

    safe_name = validate_config_name(config_name)
    staged_path = f"{STAGED_CONFIG_PREFIX}{safe_name}.conf"
    content, _mode, owner_uid = _read_regular_file(staged_path, MAX_NGINX_CONFIG_BYTES)

    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_uid is not None and owner_uid != int(sudo_uid):
        raise ValueError("staged nginx configuration is not owned by the invoking user")

    os.makedirs(NGINX_AVAILABLE_DIR, mode=0o755, exist_ok=True)
    os.makedirs(NGINX_ENABLED_DIR, mode=0o755, exist_ok=True)
    previous = _capture_nginx_paths(safe_name)
    available_path = os.path.join(NGINX_AVAILABLE_DIR, safe_name)
    enabled_path = os.path.join(NGINX_ENABLED_DIR, safe_name)

    try:
        _atomic_write(available_path, content)
        _replace_symlink(enabled_path, available_path)
        _run_checked([NGINX_BINARY, "-t"])
    except Exception:
        _restore_nginx_paths(safe_name, *previous)
        raise
    finally:
        if os.path.exists(staged_path):
            os.unlink(staged_path)


def remove_nginx_config(config_name: str) -> None:
    """Remove one validated nginx site, rolling back if validation fails."""

    safe_name = validate_config_name(config_name)
    previous = _capture_nginx_paths(safe_name)
    available_path = os.path.join(NGINX_AVAILABLE_DIR, safe_name)
    enabled_path = os.path.join(NGINX_ENABLED_DIR, safe_name)

    try:
        if os.path.lexists(enabled_path):
            os.unlink(enabled_path)
        if os.path.lexists(available_path):
            os.unlink(available_path)
        _run_checked([NGINX_BINARY, "-t"])
    except Exception:
        _restore_nginx_paths(safe_name, *previous)
        raise


def reload_nginx() -> None:
    """Validate and reload nginx."""

    _run_checked([NGINX_BINARY, "-t"])
    _run_checked([SYSTEMCTL_BINARY, "reload", "nginx.service"])


def restart_service(service_name: str) -> None:
    """Restart one generated application service."""

    _run_checked([SYSTEMCTL_BINARY, "restart", validate_service_name(service_name)])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install-nginx")
    install_parser.add_argument("config_name")

    remove_parser = subparsers.add_parser("remove-nginx")
    remove_parser.add_argument("config_name")

    subparsers.add_parser("reload-nginx")

    restart_parser = subparsers.add_parser("restart-service")
    restart_parser.add_argument("service_name")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a validated privileged deployment operation."""

    if os.geteuid() != 0:
        print("deploy admin helper must run as root", file=sys.stderr)
        return 1

    args = _build_parser().parse_args(argv)
    try:
        if args.command == "install-nginx":
            install_nginx_config(args.config_name)
        elif args.command == "remove-nginx":
            remove_nginx_config(args.config_name)
        elif args.command == "reload-nginx":
            reload_nginx()
        elif args.command == "restart-service":
            restart_service(args.service_name)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"deploy admin operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
