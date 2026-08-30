"""Shared helpers for managed HTTPS Git credentials."""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import re
import ssl
from urllib.parse import urlsplit

from lib.validators import validate_host


MAX_GIT_CA_BUNDLE_BYTES = 1024 * 1024
_PEM_CERTIFICATE_PATTERN = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+.+?\s+-----END CERTIFICATE-----",
    re.DOTALL,
)


def normalize_git_https_origin(origin: str) -> str:
    """Validate and canonicalize one credential-scoping HTTPS origin."""
    if not isinstance(origin, str) or not origin or origin != origin.strip():
        raise ValueError("Git credential origin must be a non-empty HTTPS origin")
    if any(ord(character) < 32 or ord(character) == 127 for character in origin):
        raise ValueError("Git credential origin must not contain control characters")

    parsed = urlsplit(origin)
    if parsed.scheme.lower() != "https":
        raise ValueError("Git credential origin must use https://")
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "Git credential origin must contain only a hostname and optional port"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(
            "Git credential origin must not contain a repository path, query, or fragment"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid Git credential origin host: {origin}")
    normalized_host = hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
        if not validate_host(normalized_host):
            raise ValueError(f"Invalid Git credential origin host: {hostname}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid Git credential origin port: {origin}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"Invalid Git credential origin port: {port}")

    if address is None:
        display_host = normalized_host
    else:
        display_host = f"[{address}]" if address.version == 6 else str(address)
    port_suffix = f":{port}" if port is not None and port != 443 else ""
    return f"https://{display_host}{port_suffix}"


def git_ca_filename(origin: str) -> str:
    """Return the stable managed CA filename for an HTTPS origin."""
    normalized = normalize_git_https_origin(origin)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{digest}.pem"


def encode_git_ca_pem(content: str) -> str:
    """Encode a validated PEM bundle for transport in remote setup arguments."""
    payload = content.encode("utf-8")
    if len(payload) > MAX_GIT_CA_BUNDLE_BYTES:
        raise ValueError("Git CA certificate bundle exceeds 1 MiB")
    return base64.b64encode(payload).decode("ascii")


def validate_git_ca_pem(content: str) -> str:
    """Validate and normalize a PEM certificate bundle."""
    if not isinstance(content, str) or not content:
        raise ValueError("Git CA certificate payload must be non-empty PEM text")
    if len(content.encode("utf-8")) > MAX_GIT_CA_BUNDLE_BYTES:
        raise ValueError("Git CA certificate bundle exceeds 1 MiB")
    certificates = _PEM_CERTIFICATE_PATTERN.findall(content)
    remainder = _PEM_CERTIFICATE_PATTERN.sub("", content)
    if not certificates or remainder.strip():
        raise ValueError("Git CA certificate payload must contain only PEM certificates")
    for certificate in certificates:
        try:
            ssl.PEM_cert_to_DER_cert(certificate)
        except ValueError as exc:
            raise ValueError("Git CA certificate payload contains invalid PEM") from exc
    return "\n".join(certificate.strip() for certificate in certificates) + "\n"


def decode_git_ca_pem(encoded: str) -> str:
    """Decode one bounded PEM bundle transported to the setup target."""
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("Invalid encoded Git CA certificate payload") from exc
    if not payload or len(payload) > MAX_GIT_CA_BUNDLE_BYTES:
        raise ValueError("Git CA certificate payload must be between 1 byte and 1 MiB")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Git CA certificate payload must be UTF-8 PEM text") from exc
    return validate_git_ca_pem(content)
