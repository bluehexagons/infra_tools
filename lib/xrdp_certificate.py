"""XRDP TLS certificate discovery and health checks."""

from __future__ import annotations

import configparser
import os
import pwd
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from lib.validation import validate_filesystem_path


DEFAULT_XRDP_CONFIG = "/etc/xrdp/xrdp.ini"
DEFAULT_XRDP_CERTIFICATE = "/etc/xrdp/cert.pem"
DEFAULT_XRDP_PRIVATE_KEY = "/etc/xrdp/key.pem"


@dataclass(frozen=True)
class XrdpCertificateHealth:
    """Result of checking the certificate configured for XRDP."""

    status: Literal["not_configured", "ok", "warning", "error"]
    certificate_path: str
    private_key_path: str
    details: tuple[str, ...] = ()
    fingerprint: Optional[str] = None
    expires_at: Optional[datetime] = None

    @property
    def issue(self) -> Optional[str]:
        """Return stable issue text for state-change detection."""
        if self.status not in {"warning", "error"}:
            return None
        return "\n".join(self.details)


def read_xrdp_certificate_paths(
    config_path: str = DEFAULT_XRDP_CONFIG,
) -> tuple[str, str]:
    """Return configured certificate paths, applying XRDP's defaults."""
    validate_filesystem_path(config_path, must_exist=False)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with open(config_path, encoding="utf-8") as file_obj:
            parser.read_file(file_obj)
    except (OSError, configparser.Error) as exc:
        raise ValueError(f"Cannot read XRDP configuration {config_path}: {exc}") from exc

    certificate_path = parser.get(
        "Globals", "certificate", fallback=""
    ).strip() or DEFAULT_XRDP_CERTIFICATE
    private_key_path = parser.get(
        "Globals", "key_file", fallback=""
    ).strip() or DEFAULT_XRDP_PRIVATE_KEY

    for path, label in (
        (certificate_path, "XRDP certificate"),
        (private_key_path, "XRDP private key"),
    ):
        validate_filesystem_path(path, must_exist=False)
        if not os.path.isabs(path) or os.path.normpath(path) != path:
            raise ValueError(f"{label} path must be normalized and absolute: {path}")

    return certificate_path, private_key_path


def _run_openssl(*arguments: str) -> subprocess.CompletedProcess[str]:
    openssl = shutil.which("openssl")
    if not openssl:
        return subprocess.CompletedProcess(
            ["openssl", *arguments], 127, "", "openssl is not installed"
        )
    try:
        return subprocess.run(
            [openssl, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([openssl, *arguments], 126, "", str(exc))


def _parse_certificate_metadata(output: str) -> tuple[Optional[datetime], Optional[str]]:
    expires_at: Optional[datetime] = None
    fingerprint: Optional[str] = None
    for line in output.splitlines():
        if line.startswith("notAfter="):
            value = line.split("=", 1)[1].strip()
            expires_at = datetime.strptime(
                value, "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=timezone.utc)
        elif "Fingerprint=" in line:
            fingerprint = line.split("=", 1)[1].strip().replace(":", "").lower()
    return expires_at, fingerprint


def _daemon_can_read(path: str, daemon_user: str) -> bool:
    """Check readability using the daemon's actual supplementary groups."""
    try:
        pwd.getpwnam(daemon_user)
    except KeyError:
        return False
    runuser = shutil.which("runuser")
    if not runuser:
        return False
    try:
        result = subprocess.run(
            [runuser, "-u", daemon_user, "--", "test", "-r", path],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def inspect_xrdp_certificate_pair(
    certificate_path: str,
    private_key_path: str,
    *,
    warning_days: int = 30,
    daemon_user: str = "xrdp",
    now: Optional[datetime] = None,
) -> XrdpCertificateHealth:
    """Validate certificate syntax, expiry, key match, modes, and readability."""
    errors: list[str] = []
    warnings: list[str] = []

    for path, label in (
        (certificate_path, "certificate"),
        (private_key_path, "private key"),
    ):
        validate_filesystem_path(path, must_exist=False)
        if not os.path.isfile(path):
            errors.append(f"XRDP {label} is missing or not a regular file: {path}")

    if errors:
        return XrdpCertificateHealth(
            "error", certificate_path, private_key_path, tuple(errors)
        )

    key_mode = stat.S_IMODE(os.stat(private_key_path).st_mode)
    if key_mode & 0o027:
        errors.append(
            f"XRDP private key permissions are too broad ({key_mode:04o}): "
            f"{private_key_path}"
        )

    metadata = _run_openssl(
        "x509", "-in", certificate_path, "-noout", "-enddate", "-fingerprint", "-sha256"
    )
    expires_at: Optional[datetime] = None
    fingerprint: Optional[str] = None
    if metadata.returncode != 0:
        details = metadata.stderr.strip() or "openssl could not parse the certificate"
        errors.append(f"XRDP certificate is invalid: {details}")
    else:
        try:
            expires_at, fingerprint = _parse_certificate_metadata(metadata.stdout)
        except ValueError as exc:
            errors.append(f"XRDP certificate expiry is invalid: {exc}")
        if expires_at is None:
            errors.append("XRDP certificate does not contain a parseable expiry date")
        else:
            current_time = now or datetime.now(timezone.utc)
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            if expires_at <= current_time:
                errors.append(
                    f"XRDP certificate expired at {expires_at.isoformat()}"
                )
            elif expires_at <= current_time + timedelta(days=warning_days):
                warnings.append(
                    f"XRDP certificate expires within {warning_days} days at "
                    f"{expires_at.isoformat()}"
                )

    certificate_public_key = _run_openssl(
        "x509", "-in", certificate_path, "-pubkey", "-noout"
    )
    private_public_key = _run_openssl(
        "pkey", "-in", private_key_path, "-pubout"
    )
    if certificate_public_key.returncode != 0 or private_public_key.returncode != 0:
        errors.append("XRDP certificate/private key pair could not be validated")
    elif certificate_public_key.stdout.strip() != private_public_key.stdout.strip():
        errors.append("XRDP certificate and private key do not match")

    for path, label in (
        (certificate_path, "certificate"),
        (private_key_path, "private key"),
    ):
        if not _daemon_can_read(path, daemon_user):
            errors.append(f"XRDP daemon user cannot read the {label}: {path}")

    if errors:
        status: Literal["ok", "warning", "error"] = "error"
        details = tuple(errors + warnings)
    elif warnings:
        status = "warning"
        details = tuple(warnings)
    else:
        status = "ok"
        details = ()
    return XrdpCertificateHealth(
        status,
        certificate_path,
        private_key_path,
        details,
        fingerprint,
        expires_at,
    )


def inspect_xrdp_certificate(
    config_path: str = DEFAULT_XRDP_CONFIG,
    *,
    warning_days: int = 30,
    daemon_user: str = "xrdp",
) -> XrdpCertificateHealth:
    """Inspect the effective XRDP certificate, or report no XRDP configuration."""
    if not os.path.exists(config_path):
        return XrdpCertificateHealth("not_configured", "", "")
    try:
        certificate_path, private_key_path = read_xrdp_certificate_paths(config_path)
    except ValueError as exc:
        return XrdpCertificateHealth("error", "", "", (str(exc),))
    return inspect_xrdp_certificate_pair(
        certificate_path,
        private_key_path,
        warning_days=warning_days,
        daemon_user=daemon_user,
    )
