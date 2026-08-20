#!/usr/bin/env python3
"""Small local broker for issuing provider-native device pairing links."""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import os
import re
import secrets
import socketserver
import stat
import subprocess
import threading
import time
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlsplit


MAX_REQUEST_BYTES = 4096
MAX_PROVIDER_OUTPUT_BYTES = 128 * 1024
NONCE_TTL_SECONDS = 10 * 60
RATE_WINDOW_SECONDS = 60
RATE_LIMIT = 5
MAX_RATE_SOURCES = 1024
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


class PairingError(RuntimeError):
    """A safe provider failure that may be shown without secret output."""


def _load_provider_config(path: str) -> dict[str, dict[str, Any]]:
    with open(path, encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported device-pairing provider configuration")
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, dict) or not raw_providers:
        raise ValueError("Device-pairing provider configuration is empty")

    providers: dict[str, dict[str, Any]] = {}
    for name, raw_provider in raw_providers.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,32}", name):
            raise ValueError("Invalid device-pairing provider name")
        if not isinstance(raw_provider, dict):
            raise ValueError(f"Invalid configuration for provider {name}")
        command = raw_provider.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
            or not os.path.isabs(command[0])
        ):
            raise ValueError(f"Provider {name} must use an absolute command")
        for field in ("label", "base_url_flag", "url_field", "expires_field"):
            if not isinstance(raw_provider.get(field), str) or not raw_provider[field]:
                raise ValueError(f"Provider {name} has an invalid {field}")
        public_port = raw_provider.get("public_port")
        if not isinstance(public_port, int) or isinstance(public_port, bool):
            raise ValueError(f"Provider {name} has an invalid public port")
        if not 1 <= public_port <= 65535:
            raise ValueError(f"Provider {name} has an invalid public port")
        providers[name] = raw_provider
    return providers


def _normalized_host(value: str) -> str:
    host = value.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME_RE.fullmatch(host):
            raise PairingError("The requested public host is invalid")
        return host.lower()
    return f"[{address}]" if address.version == 6 else str(address)


def _public_base_url(handler: BaseHTTPRequestHandler, port: int) -> str:
    scheme = (handler.headers.get("X-Forwarded-Proto") or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise PairingError("The requested public URL scheme is invalid")
    forwarded_host = handler.headers.get("X-Forwarded-Host") or ""
    host = _normalized_host(forwarded_host)
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{host}{suffix}"


def _safe_pairing_url(value: object, expected_base: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 8192
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PairingError("The provider did not return a pairing URL")
    parsed = urlsplit(value)
    expected = urlsplit(expected_base)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    tokens = fragment.get("token") or []
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
        or parsed.path != "/pair"
        or parsed.query
        or parsed.username is not None
        or parsed.password is not None
        or set(fragment) != {"token"}
        or len(tokens) != 1
        or not 1 <= len(tokens[0]) <= 4096
    ):
        raise PairingError("The provider returned an unexpected pairing URL")
    return value


class PairingState:
    def __init__(self, providers: dict[str, dict[str, Any]]) -> None:
        self.providers = providers
        self._lock = threading.Lock()
        self._nonces: dict[str, float] = {}
        self._requests: dict[str, list[float]] = {}

    def new_nonce(self) -> str:
        now = time.monotonic()
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._nonces = {
                key: created
                for key, created in self._nonces.items()
                if now - created <= NONCE_TTL_SECONDS
            }
            while len(self._nonces) >= 128:
                oldest = min(self._nonces, key=self._nonces.__getitem__)
                self._nonces.pop(oldest, None)
            self._nonces[nonce] = now
        return nonce

    def consume_nonce(self, nonce: str) -> bool:
        now = time.monotonic()
        with self._lock:
            created = self._nonces.pop(nonce, None)
        return created is not None and now - created <= NONCE_TTL_SECONDS

    def allow_request(self, source: str) -> bool:
        now = time.monotonic()
        with self._lock:
            active_requests: dict[str, list[float]] = {}
            for key, timestamps in self._requests.items():
                recent_timestamps = [
                    timestamp
                    for timestamp in timestamps
                    if now - timestamp <= RATE_WINDOW_SECONDS
                ]
                if recent_timestamps:
                    active_requests[key] = recent_timestamps
            self._requests = active_requests
            if source not in self._requests:
                while len(self._requests) >= MAX_RATE_SOURCES:
                    oldest = next(iter(self._requests))
                    self._requests.pop(oldest, None)
            recent = self._requests.get(source, [])
            if len(recent) >= RATE_LIMIT:
                self._requests[source] = recent
                return False
            recent.append(now)
            self._requests[source] = recent
        return True

    def issue(self, provider_name: str, base_url: str) -> tuple[str, str]:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise PairingError("Unknown device-pairing provider")
        command = [
            *provider["command"],
            provider["base_url_flag"],
            base_url,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PairingError("The pairing provider could not be started") from exc
        if result.returncode != 0:
            raise PairingError("The pairing provider could not issue a link")
        if len(result.stdout.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
            raise PairingError("The pairing provider returned too much data")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PairingError("The pairing provider returned invalid data") from exc
        if not isinstance(payload, dict):
            raise PairingError("The pairing provider returned invalid data")
        pair_url = _safe_pairing_url(payload.get(provider["url_field"]), base_url)
        expires = payload.get(provider["expires_field"])
        if not isinstance(expires, str) or len(expires) > 128:
            expires = "soon"
        return pair_url, expires


class PairingRequestHandler(BaseHTTPRequestHandler):
    server_version = "infra-tools-device-pairing"
    sys_version = ""

    @property
    def state(self) -> PairingState:
        return self.server.pairing_state  # type: ignore[attr-defined,no-any-return]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_html(
        self,
        status: HTTPStatus,
        title: str,
        body: str,
        *,
        nonce: str | None = None,
    ) -> None:
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>body{{font:16px system-ui,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1rem;color:#18202a}}main{{border:1px solid #ccd3db;border-radius:.7rem;padding:1.4rem}}button,a.button{{display:inline-block;background:#155eef;color:white;border:0;border-radius:.4rem;padding:.7rem 1rem;text-decoration:none;font:inherit;cursor:pointer}}code{{overflow-wrap:anywhere}}.muted{{color:#596574}}.error{{color:#a10f22}}</style>
</head><body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>"""
        encoded = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        if nonce is not None:
            secure = (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
            cookie = f"infra_tools_pairing_nonce={nonce}; Path=/; HttpOnly; SameSite=Strict"
            if secure:
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def _nonce_cookie(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except CookieError:
            return ""
        morsel = cookie.get("infra_tools_pairing_nonce")
        return morsel.value if morsel is not None else ""

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        nonce = self.state.new_nonce()
        buttons = []
        for name, provider in sorted(self.state.providers.items()):
            escaped_name = html.escape(name, quote=True)
            escaped_nonce = html.escape(nonce, quote=True)
            escaped_label = html.escape(provider["label"])
            buttons.append(
                f'<form method="post" action="/pair/{escaped_name}?redirect=1">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                f'<button type="submit">Pair this browser with {escaped_label}</button>'
                "</form>"
                f'<form method="post" action="/pair/{escaped_name}?redirect=0">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                f'<button type="submit">Create a link for another {escaped_label} client</button>'
                "</form>"
            )
        body = (
            "<p>Create a short-lived, one-time credential for this device. "
            "The resulting session is managed and revocable by the provider.</p>"
            + "".join(buttons)
            + "<p class=\"muted\">Do not share pairing links. Each new browser or app "
            "should create its own session.</p>"
        )
        self._send_html(HTTPStatus.OK, "Device pairing", body, nonce=nonce)

    def do_POST(self) -> None:
        parsed_path = urlsplit(self.path)
        match = re.fullmatch(r"/pair/([a-z0-9-]{1,32})", parsed_path.path)
        if match is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0]
        if content_type.strip().lower() != "application/x-www-form-urlencoded":
            self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = MAX_REQUEST_BYTES + 1
        if not 0 <= length <= MAX_REQUEST_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            form = parse_qs(
                self.rfile.read(length).decode("utf-8", errors="strict")
            )
        except UnicodeDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        submitted_nonce = (form.get("nonce") or [""])[0]
        if (
            not secrets.compare_digest(submitted_nonce, self._nonce_cookie())
            or not self.state.consume_nonce(submitted_nonce)
        ):
            self._send_html(
                HTTPStatus.FORBIDDEN,
                "Pairing request rejected",
                '<p class="error">Reload the enrollment page and try again.</p>',
            )
            return
        raw_source = (self.headers.get("X-Real-IP") or "").strip()
        try:
            source = str(ipaddress.ip_address(raw_source))
        except ValueError:
            source = "local"
        if not self.state.allow_request(source):
            self._send_html(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Pairing temporarily limited",
                "<p>Wait one minute before requesting another link.</p>",
            )
            return
        provider_name = match.group(1)
        provider = self.state.providers.get(provider_name)
        if provider is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            base_url = _public_base_url(self, provider["public_port"])
            pair_url, expires = self.state.issue(provider_name, base_url)
        except PairingError as exc:
            self._send_html(
                HTTPStatus.BAD_GATEWAY,
                "Could not create pairing link",
                f'<p class="error">{html.escape(str(exc))}</p>',
            )
            return
        redirect = parse_qs(parsed_path.query).get("redirect") == ["1"]
        if redirect:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", pair_url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return
        encoded_url = html.escape(pair_url, quote=True)
        body = (
            f'<p><a class="button" href="{encoded_url}">Pair this device</a></p>'
            f"<p><code>{html.escape(pair_url)}</code></p>"
            f'<p class="muted">Expires {html.escape(expires)}.</p>'
        )
        self._send_html(HTTPStatus.OK, "Pairing link created", body)


class ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: str, state: PairingState) -> None:
        self.pairing_state = state
        super().__init__(socket_path, PairingRequestHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="infra-tools device-pairing broker")
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()

    providers = _load_provider_config(args.config)
    socket_path = os.path.abspath(args.socket)
    socket_parent = os.path.dirname(socket_path)
    if not os.path.isdir(socket_parent):
        raise RuntimeError(f"Pairing socket directory does not exist: {socket_parent}")
    if os.path.lexists(socket_path):
        mode = os.lstat(socket_path).st_mode
        if not stat.S_ISSOCK(mode):
            raise RuntimeError(f"Refusing non-socket pairing path: {socket_path}")
        os.unlink(socket_path)

    server = ThreadingUnixServer(socket_path, PairingState(providers))
    os.chmod(socket_path, 0o660)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
