"""Explicit SSH host-key enrollment for workspace-managed connections."""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from lib.atomic_io import write_text_atomic
from lib.ssh_utils import get_workspace_known_hosts_path
from lib.validators import validate_host


_SUPPORTED_HOST_KEY_TYPES = {
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-ed25519",
    "ssh-rsa",
}


def _fingerprint(scan: str) -> str:
    result = subprocess.run(
        ["ssh-keygen", "-lf", "-"],
        input=scan,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("could not calculate the SSH host-key fingerprint")
    return result.stdout.strip()


def _known_hosts_name(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def _normalize_scan(host: str, scan: str, port: int) -> tuple[str, str]:
    """Validate scanned keys and bind every entry to the requested host."""
    expected_name = _known_hosts_name(host, port)
    normalized_lines: list[str] = []
    for raw_line in scan.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 3:
            raise RuntimeError("SSH host-key scan returned an invalid entry")
        scanned_name, key_type, key_data = fields[:3]
        if scanned_name != expected_name:
            raise RuntimeError(
                f"SSH host-key scan returned an unexpected host: {scanned_name}"
            )
        if key_type not in _SUPPORTED_HOST_KEY_TYPES:
            raise RuntimeError(
                f"SSH host-key scan returned an unsupported key type: {key_type}"
            )
        normalized_lines.append(f"{expected_name} {key_type} {key_data}")
    if not normalized_lines:
        raise RuntimeError("SSH host-key scan returned no usable keys")

    normalized = "\n".join(normalized_lines)
    return normalized, _fingerprint(normalized)


def _matching_known_host_lines(path: str, host_name: str) -> set[str]:
    """Return plain or hashed known_hosts entries matching ``host_name``."""
    result = subprocess.run(
        ["ssh-keygen", "-F", host_name, "-f", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError("could not inspect existing SSH host keys")
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("#")
    }


def _persist_scan(host: str, scan: str, port: int) -> str:
    known_hosts = get_workspace_known_hosts_path()
    os.makedirs(os.path.dirname(known_hosts), mode=0o700, exist_ok=True)

    existing_lines: list[str] = []
    if os.path.exists(known_hosts):
        with open(known_hosts, encoding="utf-8") as file_obj:
            existing_lines = file_obj.read().splitlines()
    if existing_lines:
        matches = _matching_known_host_lines(
            known_hosts,
            _known_hosts_name(host, port),
        )
        existing_lines = [line for line in existing_lines if line.strip() not in matches]

    updated_lines = [*existing_lines, *scan.splitlines()]
    write_text_atomic(known_hosts, "\n".join(updated_lines) + "\n", mode=0o600)
    return known_hosts


def replace_scanned_host_keys(host: str, scan: str, *, port: int = 22) -> str:
    """Replace a workspace host's keys with an already trusted key scan."""
    if not validate_host(host):
        raise ValueError(f"Invalid host: {host}")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    normalized_scan, _fingerprints = _normalize_scan(host, scan, port)
    return _persist_scan(host, normalized_scan, port)


def enroll_host_key(
    host: str,
    *,
    port: int = 22,
    assume_yes: bool = False,
    input_fn: Optional[Callable[[str], str]] = None,
) -> int:
    """Scan, display, and optionally persist a host key after confirmation."""
    if not validate_host(host):
        raise ValueError(f"Invalid host: {host}")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")

    result = subprocess.run(
        [
            "ssh-keyscan",
            "-T",
            "10",
            "-t",
            "ed25519",
            "-p",
            str(port),
            host,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    scan = result.stdout.strip()
    if result.returncode != 0 or not scan:
        detail = result.stderr.strip() or "no host key was returned"
        print(f"Error enrolling {host}: {detail}")
        return 1

    try:
        normalized_scan, fingerprints = _normalize_scan(host, scan, port)
    except RuntimeError as exc:
        print(f"Error enrolling {host}: {exc}")
        return 1

    print(f"SSH host-key fingerprint for {host}:{port}:")
    print(fingerprints)
    if not assume_yes:
        response = (input_fn or input)(
            "Verify this fingerprint out of band and enroll it? [y/N] "
        )
        if response.strip().lower() not in {"y", "yes"}:
            print("Cancelled; no host key was saved.")
            return 1

    known_hosts = _persist_scan(host, normalized_scan, port)
    print(f"Enrolled host key in {known_hosts}")
    print(
        "Plain ssh uses ~/.ssh/known_hosts unless configured to use the "
        "infra-tools workspace file."
    )
    return 0
