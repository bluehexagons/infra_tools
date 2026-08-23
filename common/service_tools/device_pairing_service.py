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
import signal
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
MAX_CONNECT_OUTPUT_BYTES = 64 * 1024
MAX_CONNECT_INPUT_BYTES = 512
NONCE_TTL_SECONDS = 10 * 60
CONNECT_JOB_TTL_SECONDS = 15 * 60
RATE_WINDOW_SECONDS = 60
RATE_LIMIT = 5
MAX_RATE_SOURCES = 1024
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONNECT_URL_RE = re.compile(r"https?://[^\s<>]+")


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
            or any("\x00" in part for part in command if isinstance(part, str))
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
        https_public_port = raw_provider.get("https_public_port")
        if https_public_port is not None and (
            not isinstance(https_public_port, int)
            or isinstance(https_public_port, bool)
            or not 1024 <= https_public_port <= 65535
        ):
            raise ValueError(f"Provider {name} has an invalid HTTPS public port")
        connect = raw_provider.get("connect")
        if connect is not None:
            if not isinstance(connect, dict):
                raise ValueError(f"Provider {name} has an invalid T3 Connect configuration")
            for key in ("link_command", "status_command", "unlink_command"):
                command_value = connect.get(key)
                if (
                    not isinstance(command_value, list)
                    or not command_value
                    or not all(isinstance(part, str) and part for part in command_value)
                    or any(
                        "\x00" in part
                        for part in command_value
                        if isinstance(part, str)
                    )
                    or not os.path.isabs(command_value[0])
                ):
                    raise ValueError(f"Provider {name} has an invalid T3 Connect {key}")
            restart_request = connect.get("restart_request")
            if (
                not isinstance(restart_request, str)
                or not os.path.isabs(restart_request)
                or len(restart_request) > 4096
                or "\x00" in restart_request
            ):
                raise ValueError(f"Provider {name} has an invalid T3 Connect restart request")
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


def _public_base_url(
    handler: BaseHTTPRequestHandler,
    port: int,
    https_port: int | None = None,
) -> str:
    scheme = (handler.headers.get("X-Forwarded-Proto") or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise PairingError("The requested public URL scheme is invalid")
    forwarded_host = handler.headers.get("X-Forwarded-Host") or ""
    try:
        parsed_host = urlsplit(f"//{forwarded_host}")
        host = _normalized_host(parsed_host.hostname or "")
    except ValueError as exc:
        raise PairingError("The requested public host is invalid") from exc
    effective_port = https_port if scheme == "https" and https_port else port
    default_port = 443 if scheme == "https" else 80
    suffix = "" if effective_port == default_port else f":{effective_port}"
    return f"{scheme}://{host}{suffix}"


def _safe_pairing_url(value: object, expected_base: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 8192
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PairingError("The provider did not return a pairing URL")
    try:
        parsed = urlsplit(value)
        expected = urlsplit(expected_base)
    except ValueError as exc:
        raise PairingError("The provider returned an unexpected pairing URL") from exc
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


class ConnectJob:
    """Run the interactive headless Connect command without logging its output."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._output = ""
        self._started_at = 0.0
        self._finished_at: float | None = None
        self._returncode: int | None = None
        self._error: str | None = None

    def _append_output(self, text: str) -> None:
        clean = _ANSI_ESCAPE_RE.sub("", text).replace("\r", "")
        with self._lock:
            self._output = (self._output + clean)[-MAX_CONNECT_OUTPUT_BYTES:]

    def _watch(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for chunk in iter(lambda: process.stdout.read(1), ""):
                if chunk:
                    self._append_output(chunk)
            returncode = process.wait()
        except OSError:
            returncode = process.poll()
        finally:
            process.stdout.close()
            if process.stdin is not None:
                process.stdin.close()
        with self._lock:
            self._returncode = returncode if returncode is not None else 1
            self._finished_at = time.monotonic()
            self._process = None
        if returncode == 0:
            request_path = self.config["restart_request"]
            try:
                descriptor = os.open(
                    request_path,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                os.close(descriptor)
            except OSError:
                with self._lock:
                    self._error = (
                        "Connect completed, but the T3 service restart "
                        "could not be requested"
                    )

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                raise PairingError("A T3 Connect operation is already running")
            if self._finished_at is not None and (
                time.monotonic() - self._finished_at < CONNECT_JOB_TTL_SECONDS
            ):
                raise PairingError(
                    "Finish or reload the current T3 Connect operation first"
                )
            self._output = ""
            self._error = None
            self._returncode = None
            self._finished_at = None
            self._started_at = time.monotonic()
            try:
                process = subprocess.Popen(
                    self.config["link_command"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    bufsize=1,
                    env=os.environ.copy(),
                    start_new_session=True,
                )
            except (OSError, ValueError) as exc:
                raise PairingError("T3 Connect could not be started") from exc
            self._process = process
        threading.Thread(target=self._watch, args=(process,), daemon=True).start()

    def send_input(self, value: str) -> None:
        encoded = value.encode("utf-8")
        if (
            not value
            or len(encoded) > MAX_CONNECT_INPUT_BYTES
            or any(
                ord(character) < 32 and character not in "\t"
                for character in value
            )
        ):
            raise PairingError("T3 Connect input is invalid")
        with self._lock:
            process = self._process
        if process is None or process.stdin is None:
            raise PairingError("No T3 Connect operation is waiting for input")
        try:
            process.stdin.write(value + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise PairingError(
                "The T3 Connect operation is no longer running"
            ) from exc

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            process = self._process
            output = self._output
            returncode = self._returncode
            error = self._error
            started_at = self._started_at
        if process is not None and time.monotonic() - started_at > CONNECT_JOB_TTL_SECONDS:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            error = "The T3 Connect operation expired; start it again"
        return {
            "active": process is not None,
            "error": error,
            "output": output,
            "returncode": returncode,
        }


def _connect_output_html(output: str) -> str:
    """Render only validated HTTP(S) URLs in CLI output as links."""

    rendered: list[str] = []
    cursor = 0
    for match in _CONNECT_URL_RE.finditer(output):
        value = match.group(0).rstrip(".,)")
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(ord(character) < 32 for character in value)
        ):
            continue
        rendered.append(html.escape(output[cursor : match.start()]))
        escaped = html.escape(value, quote=True)
        rendered.append(
            f'<a href="{escaped}" target="_blank" rel="noopener">'
            f"{html.escape(value)}</a>"
        )
        if len(value) < len(match.group(0)):
            rendered.append(html.escape(match.group(0)[len(value) :]))
        cursor = match.end()
    rendered.append(html.escape(output[cursor:]))
    return "".join(rendered)


class PairingState:
    def __init__(self, providers: dict[str, dict[str, Any]]) -> None:
        self.providers = providers
        self._lock = threading.Lock()
        self._nonces: dict[str, float] = {}
        self._requests: dict[str, list[float]] = {}
        self._connect_jobs: dict[str, ConnectJob] = {
            name: ConnectJob(provider["connect"])
            for name, provider in providers.items()
            if isinstance(provider.get("connect"), dict)
        }

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

    def connect_snapshot(self, provider_name: str) -> dict[str, object]:
        job = self._connect_jobs.get(provider_name)
        if job is None:
            raise PairingError("T3 Connect is not configured")
        snapshot = job.snapshot()
        try:
            result = subprocess.run(
                job.config["status_command"],
                check=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                env=os.environ.copy(),
            )
            if (
                result.returncode == 0
                and len(result.stdout.encode("utf-8")) <= MAX_PROVIDER_OUTPUT_BYTES
            ):
                payload = json.loads(result.stdout)
                if isinstance(payload, dict):
                    snapshot["status"] = {
                        key: payload.get(key)
                        for key in (
                            "desired",
                            "authenticated",
                            "linked",
                            "provisioned",
                            "relayUrl",
                            "publishEnabled",
                        )
                        if isinstance(payload.get(key), (bool, str))
                        or payload.get(key) is None
                    }
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return snapshot

    def start_connect(self, provider_name: str) -> None:
        job = self._connect_jobs.get(provider_name)
        if job is None:
            raise PairingError("T3 Connect is not configured")
        job.start()

    def send_connect_input(self, provider_name: str, value: str) -> None:
        job = self._connect_jobs.get(provider_name)
        if job is None:
            raise PairingError("T3 Connect is not configured")
        job.send_input(value)

    def unlink_connect(self, provider_name: str) -> None:
        provider = self.providers.get(provider_name)
        if provider is None or not isinstance(provider.get("connect"), dict):
            raise PairingError("T3 Connect is not configured")
        job = self._connect_jobs[provider_name]
        if job.snapshot()["active"]:
            raise PairingError("Finish the current T3 Connect operation first")
        try:
            result = subprocess.run(
                job.config["unlink_command"],
                check=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
                env=os.environ.copy(),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise PairingError("T3 Connect could not be disabled") from exc
        if result.returncode != 0:
            raise PairingError("T3 Connect could not be disabled")
        try:
            descriptor = os.open(
                job.config["restart_request"],
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            os.close(descriptor)
        except OSError as exc:
            raise PairingError(
                "T3 Connect was disabled, but the T3 service restart "
                "could not be requested"
            ) from exc


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

    def _connect_section(
        self,
        name: str,
        provider: dict[str, Any],
        nonce: str,
        *,
        error: str | None = None,
    ) -> str:
        snapshot = self.state.connect_snapshot(name)
        status = snapshot.get("status")
        status_items: list[str] = []
        if isinstance(status, dict):
            for key, label in (
                ("authenticated", "Authorized"),
                ("linked", "Linked"),
                ("provisioned", "Tunnel active"),
            ):
                value = status.get(key)
                if isinstance(value, bool):
                    status_items.append(f"{label}: {'yes' if value else 'no'}")
            relay_url = status.get("relayUrl")
            if isinstance(relay_url, str) and relay_url:
                status_items.append(f"Relay: {html.escape(relay_url)}")
        status_text = ", ".join(status_items) or "Status is not available yet"
        output = str(snapshot.get("output") or "")
        output_block = f"<pre>{_connect_output_html(output)}</pre>" if output else ""
        error_text = error or snapshot.get("error")
        error_block = (
            f'<p class="error">{html.escape(str(error_text))}</p>'
            if error_text
            else ""
        )
        escaped_name = html.escape(name, quote=True)
        escaped_nonce = html.escape(nonce, quote=True)
        active = bool(snapshot.get("active"))
        enabled = bool(isinstance(status, dict) and status.get("desired"))
        if active:
            action = (
                f'<form method="post" action="/connect/{escaped_name}">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                '<input type="hidden" name="intent" value="input">'
                '<label>Next command response or authorization code '
                '<input name="input" maxlength="512" autocomplete="off" required></label> '
                '<button type="submit">Send</button></form>'
            )
        else:
            checked = " checked" if enabled else ""
            action = (
                f'<form method="post" action="/connect/{escaped_name}">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                '<input type="hidden" name="intent" value="toggle">'
                f'<label><input type="checkbox" name="enabled"{checked}> '
                'Enable T3 Connect tunnel</label> '
                '<button type="submit">Apply</button></form>'
            )
        refresh = '<meta http-equiv="refresh" content="2">' if active else ""
        return (
            f"{refresh}<section><h2>T3 Connect</h2>"
            "<p>Authorize this machine with T3 Connect. T3 installs its pinned "
            "relay client when requested and the managed T3 service starts the "
            "tunnel after authorization.</p>"
            f"<p class=\"muted\">{status_text}</p>{error_block}{output_block}"
            + (
                action
                if active or not enabled
                else action
            )
            + (
                ""
                if active
                else (
                    f'<form method="post" action="/connect/{escaped_name}">'
                    f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                    '<input type="hidden" name="intent" value="start">'
                    '<button type="submit">Set up or re-authorize T3 Connect</button></form>'
                )
            )
            + "</section>"
        )

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        nonce = self.state.new_nonce()
        buttons = []
        connect_sections = []
        for name, provider in sorted(self.state.providers.items()):
            escaped_name = html.escape(name, quote=True)
            escaped_nonce = html.escape(nonce, quote=True)
            escaped_label = html.escape(provider["label"])
            buttons.append(
                f'<form method="post" action="/pair/{escaped_name}">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                '<input type="hidden" name="intent" value="current">'
                f'<button type="submit">Create a link for this browser with {escaped_label}</button>'
                "</form>"
                f'<form method="post" action="/pair/{escaped_name}">'
                f'<input type="hidden" name="nonce" value="{escaped_nonce}">'
                '<input type="hidden" name="intent" value="other">'
                f'<button type="submit">Create a link for another {escaped_label} client</button>'
                "</form>"
            )
            if name in self.state._connect_jobs:
                connect_sections.append(
                    self._connect_section(name, provider, nonce)
                )
        body = (
            "<p>Create a short-lived, one-time credential for this device. "
            "The resulting session is managed and revocable by the provider.</p>"
            + "".join(buttons)
            + "<p class=\"muted\">Do not share pairing links. Each new browser or app "
            "should create its own session.</p>"
            + "".join(connect_sections)
        )
        self._send_html(HTTPStatus.OK, "Device pairing", body, nonce=nonce)

    def do_POST(self) -> None:
        parsed_path = urlsplit(self.path)
        match = re.fullmatch(r"/(pair|connect)/([a-z0-9-]{1,32})", parsed_path.path)
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
        intent = (form.get("intent") or [""])[0]
        if (
            not secrets.compare_digest(submitted_nonce, self._nonce_cookie())
            or not self.state.consume_nonce(submitted_nonce)
            or intent not in {"current", "other", "start", "input", "toggle"}
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
        if intent != "input" and not self.state.allow_request(source):
            self._send_html(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Pairing temporarily limited",
                "<p>Wait one minute before requesting another link.</p>",
            )
            return
        provider_name = match.group(2)
        provider = self.state.providers.get(provider_name)
        if provider is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if match.group(1) == "connect":
            if provider_name not in self.state._connect_jobs:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                if intent == "start":
                    self.state.start_connect(provider_name)
                elif intent == "input":
                    self.state.send_connect_input(
                        provider_name,
                        (form.get("input") or [""])[0],
                    )
                elif intent == "toggle":
                    if (form.get("enabled") or [""])[0] == "on":
                        self.state.start_connect(provider_name)
                    else:
                        self.state.unlink_connect(provider_name)
            except PairingError as exc:
                nonce = self.state.new_nonce()
                self._send_html(
                    HTTPStatus.BAD_REQUEST,
                    "T3 Connect action failed",
                    self._connect_section(provider_name, provider, nonce, error=str(exc)),
                    nonce=nonce,
                )
                return
            nonce = self.state.new_nonce()
            self._send_html(
                HTTPStatus.OK,
                "T3 Connect",
                self._connect_section(provider_name, provider, nonce),
                nonce=nonce,
            )
            return
        try:
            base_url = _public_base_url(
                self,
                provider["public_port"],
                provider.get("https_public_port"),
            )
            pair_url, expires = self.state.issue(provider_name, base_url)
        except PairingError as exc:
            self._send_html(
                HTTPStatus.BAD_GATEWAY,
                "Could not create pairing link",
                f'<p class="error">{html.escape(str(exc))}</p>',
            )
            return
        encoded_url = html.escape(pair_url, quote=True)
        link_label = (
            f"Pair this browser with {html.escape(provider['label'])}"
            if intent == "current"
            else "Open pairing link"
        )
        body = (
            '<p>Use the button below to continue. This explicit browser navigation '
            'preserves the one-time pairing credential across the service port change.</p>'
            f'<p><a class="button" href="{encoded_url}">{link_label}</a></p>'
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
