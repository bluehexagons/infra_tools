#!/usr/bin/env python3
"""Pull file-backed agent credentials from a provisioned VM over SSH."""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Sequence


MAX_CREDENTIAL_BYTES = 4 * 1024 * 1024
AUTH_FILES = {
    "gh": (".config/gh/hosts.yml", "gh-hosts.yml"),
    "codex": (".codex/auth.json", "codex-auth.json"),
    "claude": (".claude/.credentials.json", "claude-credentials.json"),
    "opencode": (".local/share/opencode/auth.json", "opencode-auth.json"),
}

_REMOTE_READ_SCRIPT = r"""
import os, stat, sys

relative_path = sys.argv[1]
limit = int(sys.argv[2])
home = os.environ.get("HOME", "")
if not os.path.isabs(home):
    print("remote home directory is unavailable", file=sys.stderr)
    raise SystemExit(4)

current = home
for component in relative_path.split("/"):
    current = os.path.join(current, component)
    try:
        details = os.lstat(current)
    except FileNotFoundError:
        print("credential file is not present", file=sys.stderr)
        raise SystemExit(3)
    if stat.S_ISLNK(details.st_mode):
        print("credential path contains a symbolic link", file=sys.stderr)
        raise SystemExit(4)

details = os.lstat(current)
if not stat.S_ISREG(details.st_mode):
    print("credential path is not a regular file", file=sys.stderr)
    raise SystemExit(4)
if details.st_uid != os.geteuid():
    print("credential file is not owned by the remote user", file=sys.stderr)
    raise SystemExit(4)
if details.st_mode & 0o077:
    print("credential file is accessible by other users", file=sys.stderr)
    raise SystemExit(4)
if not 0 < details.st_size <= limit:
    print("credential file is empty or exceeds the size limit", file=sys.stderr)
    raise SystemExit(4)

flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(current, flags)
try:
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or opened.st_mode & 0o077
        or opened.st_dev != details.st_dev
        or opened.st_ino != details.st_ino
        or not 0 < opened.st_size <= limit
    ):
        print("credential file changed during validation", file=sys.stderr)
        raise SystemExit(4)
    payload = bytearray()
    while len(payload) <= limit:
        chunk = os.read(descriptor, min(65536, limit + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    finished = os.fstat(descriptor)
finally:
    os.close(descriptor)

if (
    not payload
    or len(payload) > limit
    or len(payload) != opened.st_size
    or finished.st_size != opened.st_size
    or finished.st_mtime_ns != opened.st_mtime_ns
    or finished.st_ctime_ns != opened.st_ctime_ns
):
    print("credential payload changed while it was being read", file=sys.stderr)
    raise SystemExit(4)
sys.stdout.buffer.write(bytes(payload))
"""


def _fallback_validate_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    normalized = host.lower().removesuffix(".")
    if not normalized or len(normalized) > 253:
        return False
    label = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)
    return all(label.fullmatch(part) for part in normalized.split("."))


def _validate_connection(host: str, username: str, port: int) -> None:
    try:
        from lib.validators import validate_host, validate_username
    except ModuleNotFoundError:
        host_valid = _fallback_validate_host(host)
        username_valid = bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username))
    else:
        host_valid = validate_host(host)
        username_valid = validate_username(username)
    if not host_valid:
        raise ValueError(f"invalid SSH host: {host}")
    if not username_valid:
        raise ValueError(f"invalid SSH username: {username}")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")


def _validate_key(path: str | None) -> str | None:
    if path is None:
        return None
    expanded = os.path.abspath(os.path.expanduser(path))
    try:
        from lib.validation import validate_filesystem_path
    except ModuleNotFoundError:
        pass
    else:
        validate_filesystem_path(expanded, must_exist=True)
    details = os.lstat(expanded)
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise ValueError(f"SSH key must be a regular, non-symlink file: {expanded}")
    return expanded


def _private_output_directory(path: str) -> Path:
    expanded = Path(path).expanduser().absolute()
    try:
        from lib.validation import validate_filesystem_path
    except ModuleNotFoundError:
        pass
    else:
        validate_filesystem_path(str(expanded), must_exist=False)
    if expanded.exists() or expanded.is_symlink():
        details = expanded.lstat()
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise ValueError(f"output path must be a non-symlink directory: {expanded}")
        if details.st_uid != os.geteuid():
            raise ValueError(f"output directory is not owned by the current user: {expanded}")
        if details.st_mode & 0o077:
            raise ValueError(f"output directory must not be accessible by other users: {expanded}")
    else:
        expanded.mkdir(mode=0o700, parents=True)
        os.chmod(expanded, 0o700)
    return expanded


def _ssh_command(
    host: str,
    username: str,
    port: int,
    ssh_key: str | None,
    remote_path: str,
) -> list[str]:
    remote_command = "python3 -c {} {} {}".format(
        shlex.quote(_REMOTE_READ_SCRIPT),
        shlex.quote(remote_path),
        MAX_CREDENTIAL_BYTES,
    )
    command = ["ssh", "-T", "-p", str(port)]
    if ssh_key:
        command.extend(("-i", ssh_key))
    command.extend(("--", f"{username}@{host}", remote_command))
    return command


def _read_remote_credential(
    host: str,
    username: str,
    port: int,
    ssh_key: str | None,
    remote_path: str,
) -> bytes | None:
    command = _ssh_command(host, username, port, ssh_key, remote_path)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SSH credential transfer timed out") from exc
    if result.returncode == 3:
        return None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail[:500] or "SSH credential transfer failed")
    if not 0 < len(result.stdout) <= MAX_CREDENTIAL_BYTES:
        raise RuntimeError("received an empty or oversized credential payload")
    return result.stdout


def _write_credential(destination: Path, payload: bytes, overwrite: bool) -> None:
    if destination.exists() or destination.is_symlink():
        details = destination.lstat()
        if not overwrite:
            raise FileExistsError(f"destination already exists: {destination}")
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise ValueError(f"refusing to replace non-regular destination: {destination}")
        if details.st_uid != os.geteuid():
            raise ValueError(f"destination is not owned by the current user: {destination}")

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        os.chmod(destination, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def pull_credentials(
    *,
    host: str,
    username: str,
    output_dir: str,
    tools: Sequence[str] | None = None,
    port: int = 22,
    ssh_key: str | None = None,
    overwrite: bool = False,
) -> int:
    """Pull selected credentials without displaying their contents."""
    _validate_connection(host, username, port)
    selected = list(dict.fromkeys(tools or AUTH_FILES))
    unknown = [tool for tool in selected if tool not in AUTH_FILES]
    if unknown:
        raise ValueError(f"unsupported agent credential: {unknown[0]}")
    if shutil.which("ssh") is None:
        raise RuntimeError("OpenSSH client is required (ssh was not found)")
    validated_key = _validate_key(ssh_key)
    destination_dir = _private_output_directory(output_dir)
    explicitly_selected = bool(tools)
    pulled = 0
    failed = 0

    for tool in selected:
        remote_path, local_name = AUTH_FILES[tool]
        try:
            payload = _read_remote_credential(
                host, username, port, validated_key, remote_path
            )
            if payload is None:
                print(f"Skipped {tool}: credential file is not present on the VM")
                if explicitly_selected:
                    failed += 1
                continue
            destination = destination_dir / local_name
            _write_credential(destination, payload, overwrite)
            print(f"Pulled {tool} credentials to {destination}")
            pulled += 1
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {tool}: {exc}", file=sys.stderr)
            failed += 1

    if pulled == 0:
        print("Error: no credential files were pulled", file=sys.stderr)
        return 1
    return 1 if failed else 0


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pull file-backed gh, Codex, Claude Code, and OpenCode credentials "
            "from a provisioned agent VM without printing their contents."
        )
    )
    parser.add_argument("host", metavar="HOST", help="Previously provisioned agent VM")
    parser.add_argument("username", metavar="USER", help="Agent VM SSH user")
    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="PATH",
        help="Private controller-local directory for pulled files",
    )
    parser.add_argument(
        "--tool",
        action="append",
        choices=tuple(AUTH_FILES),
        help="Credential to pull; repeat as needed (default: every present file)",
    )
    parser.add_argument("-i", "--key", dest="ssh_key", help="SSH private key path")
    parser.add_argument("-p", "--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Deliberately replace existing regular credential files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        return pull_credentials(
            host=args.host,
            username=args.username,
            output_dir=args.output_dir,
            tools=args.tool,
            port=args.port,
            ssh_key=args.ssh_key,
            overwrite=args.overwrite,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
