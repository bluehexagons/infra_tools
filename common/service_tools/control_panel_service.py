#!/usr/bin/env python3
"""Serve the authenticated infra-tools control panel behind Nginx."""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import shutil
import socketserver
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


_MAX_CONFIG_BYTES = 256 * 1024
_MAX_REQUEST_BYTES = 16 * 1024
_MAX_OUTPUT_BYTES = 24 * 1024
_T3_UPDATE_TIMEOUT_SECONDS = 30 * 60
_T3_UPDATE_SCRIPT = r'''
set -eu
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then . "$NVM_DIR/nvm.sh"; fi
export PATH="$HOME/.local/share/infra-tools/t3-npm/bin:$PATH"
unset npm_config_dangerously_allow_all_scripts
unset NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS
unset npm_config_allow_scripts
unset NPM_CONFIG_ALLOW_SCRIPTS
export CC=gcc
export CXX=g++
export npm_config_strict_allow_scripts=false
export npm_config_foreground_scripts=true
npx --yes --package=t3@latest -c \
  'env -u npm_config_allow_scripts \
    -u NPM_CONFIG_ALLOW_SCRIPTS \
    -u npm_config_dangerously_allow_all_scripts \
    -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
    t3 service update'
'''.strip()


def _subprocess_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _load_manifest(path: str) -> dict[str, Any]:
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError(f"Control-panel manifest must be a regular file: {path}")
    if os.path.getsize(path) > _MAX_CONFIG_BYTES:
        raise RuntimeError("Control-panel manifest exceeds the size limit")
    with open(path, encoding="utf-8") as file_obj:
        value = json.load(file_obj)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("Invalid control-panel manifest")
    for name in ("host", "system_type", "username"):
        if not isinstance(value.get(name), str) or not value[name]:
            raise RuntimeError(f"Control-panel manifest has no valid {name}")
    for name in ("services", "access"):
        if not isinstance(value.get(name), list):
            raise RuntimeError(f"Control-panel manifest has no valid {name}")
    if not isinstance(value.get("features"), dict):
        raise RuntimeError("Control-panel manifest has no valid features")
    return value


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None
    return value


def _run_json(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > _MAX_CONFIG_BYTES:
        return {}
    try:
        value = json.loads(result.stdout)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def discover_infra_web_services() -> list[dict[str, str]]:
    """Return live routes owned by the control-panel service user."""

    utility = shutil.which("infra-web")
    if not utility:
        return []
    services: list[dict[str, str]] = []
    for command, collection, name_field, label_prefix in (
        ([utility, "forward", "list", "--json"], "forwards", "name", "HTTPS service"),
        ([utility, "site", "list", "--json"], "sites", "name", "Published site"),
    ):
        payload = _run_json(command)
        records = payload.get(collection)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            url = _safe_url(record.get("url"))
            name = record.get(name_field)
            if url and isinstance(name, str) and name:
                services.append(
                    {
                        "label": f"{label_prefix}: {name}",
                        "url": url,
                        "description": "live" if record.get("ready", True) else "not responding",
                    }
                )
    return services


def _deduplicate_services(
    configured: list[object], dynamic: list[dict[str, str]]
) -> list[dict[str, str]]:
    services: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in [*configured, *dynamic]:
        if not isinstance(record, dict):
            continue
        url = _safe_url(record.get("url"))
        label = record.get("label")
        if not url or not isinstance(label, str) or not label or url in seen:
            continue
        description = record.get("description")
        services.append(
            {
                "label": label,
                "url": url,
                "description": description if isinstance(description, str) else "",
            }
        )
        seen.add(url)
    return services


class ControlPanelState:
    """In-memory state for bounded maintenance actions."""

    def __init__(self, manifest: dict[str, Any]) -> None:
        self.manifest = manifest
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self.action_status = "idle"
        self.action_message = ""
        self.action_output = ""

    def t3_update_available(self) -> bool:
        """Return whether T3 Code is both configured and present for this user."""

        return bool(
            self.manifest["features"].get("t3_update")
            and os.path.isdir(os.path.expanduser("~/.t3/runtime"))
        )

    def trigger_t3_update(self) -> bool:
        if not self.t3_update_available():
            return False
        with self._lock:
            if self.action_status == "running":
                return False
            self.action_status = "running"
            self.action_message = "Updating T3 Code…"
            self.action_output = ""
        threading.Thread(target=self._run_t3_update, daemon=True).start()
        return True

    def _run_t3_update(self) -> None:
        home = os.path.expanduser("~")
        environment = os.environ.copy()
        environment.setdefault("HOME", home)
        environment.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        environment.setdefault(
            "DBUS_SESSION_BUS_ADDRESS",
            f"unix:path=/run/user/{os.getuid()}/bus",
        )
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", _T3_UPDATE_SCRIPT],
                check=False,
                capture_output=True,
                text=True,
                timeout=_T3_UPDATE_TIMEOUT_SECONDS,
                cwd=home,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            output = _subprocess_text(exc.stdout) + _subprocess_text(exc.stderr)
            self._finish_action("failed", "T3 Code update timed out.", output)
            return
        except OSError as exc:
            self._finish_action("failed", "T3 Code updater could not start.", str(exc))
            return

        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            self._finish_action(
                "failed",
                f"T3 Code update failed with exit code {result.returncode}.",
                output,
            )
            return

        doctor = shutil.which("infra-tools")
        if doctor:
            try:
                check = subprocess.run(
                    [doctor, "agent", "doctor", "--capability", "t3code", "--fix"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=home,
                    env=environment,
                )
            except subprocess.TimeoutExpired as exc:
                output += _subprocess_text(exc.stdout) + _subprocess_text(exc.stderr)
                self._finish_action(
                    "failed",
                    "T3 Code updated, but its readiness check timed out.",
                    output,
                )
                return
            except OSError as exc:
                self._finish_action(
                    "failed",
                    "T3 Code updated, but its readiness check could not start.",
                    output + str(exc),
                )
                return
            output += (check.stdout or "") + (check.stderr or "")
            if check.returncode != 0:
                self._finish_action(
                    "failed",
                    "T3 Code updated, but its readiness check failed.",
                    output,
                )
                return
        self._finish_action("complete", "T3 Code update completed.", output)

    def _finish_action(self, status: str, message: str, output: str) -> None:
        encoded = output.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_OUTPUT_BYTES:
            encoded = encoded[-_MAX_OUTPUT_BYTES:]
            output = "… earlier output omitted …\n" + encoded.decode(
                "utf-8", errors="replace"
            )
        with self._lock:
            self.action_status = status
            self.action_message = message
            self.action_output = output.strip()


def render_page(state: ControlPanelState) -> str:
    """Render a small no-JavaScript dashboard from current capability state."""

    manifest = state.manifest
    services = _deduplicate_services(
        manifest["services"], discover_infra_web_services()
    )
    service_cards = "".join(
        '<a class="card" href="{}"><strong>{}</strong><span>{}</span></a>'.format(
            html.escape(record["url"], quote=True),
            html.escape(record["label"]),
            html.escape(record["description"] or record["url"]),
        )
        for record in services
    ) or '<p class="empty">No hosted web services were detected.</p>'

    access_rows = "".join(
        "<li><strong>{}</strong><code>{}</code><span>{}</span></li>".format(
            html.escape(str(record.get("label", "Access"))),
            html.escape(str(record.get("value", ""))),
            html.escape(str(record.get("description", ""))),
        )
        for record in manifest["access"]
        if isinstance(record, dict) and record.get("value")
    )

    action = ""
    if state.t3_update_available():
        disabled = " disabled" if state.action_status == "running" else ""
        action = f'''<section><h2>Maintenance</h2>
<div class="action"><div><strong>T3 Code</strong><p>Install the latest upstream release and verify the managed service.</p></div>
<form method="post" action="/actions/t3-update">
<input type="hidden" name="csrf" value="{html.escape(state.csrf_token, quote=True)}">
<button type="submit"{disabled}>Update T3 Code</button></form></div></section>'''

    status = ""
    if state.action_message:
        output = (
            f"<details><summary>Command output</summary><pre>{html.escape(state.action_output)}</pre></details>"
            if state.action_output
            else ""
        )
        status = (
            f'<aside class="status {html.escape(state.action_status)}">'
            f"{html.escape(state.action_message)}{output}</aside>"
        )

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(manifest.get("title") or "infra-tools control panel")}</title>
<style>
:root{{--bg:#f6f7f9;--panel:#fff;--text:#18202a;--muted:#667085;--line:#dde2e8;--accent:#2859c5;--ok:#176b3a;--bad:#a12a2a}}@media(prefers-color-scheme:dark){{:root{{--bg:#11151a;--panel:#181e25;--text:#edf2f7;--muted:#a5afbd;--line:#303944;--accent:#87aaff;--ok:#72d69a;--bad:#ff9999}}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,sans-serif}}main{{max-width:880px;margin:auto;padding:48px 20px 72px}}header{{margin-bottom:36px}}h1{{font-size:clamp(1.8rem,5vw,2.7rem);margin:0 0 5px;letter-spacing:-.04em}}h2{{font-size:1rem;margin:34px 0 14px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}p{{margin:.25rem 0;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.card{{display:flex;flex-direction:column;gap:3px;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--text);text-decoration:none}}.card:hover{{border-color:var(--accent)}}.card span,.empty,li span{{color:var(--muted);font-size:.9rem}}ul{{list-style:none;padding:0;margin:0;border:1px solid var(--line);border-radius:10px;background:var(--panel)}}li{{display:grid;grid-template-columns:130px 1fr;gap:4px 16px;padding:13px 16px;border-bottom:1px solid var(--line)}}li:last-child{{border:0}}li span{{grid-column:2}}code{{overflow-wrap:anywhere}}.action{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}}button{{border:0;border-radius:8px;background:var(--accent);color:white;font-weight:700;padding:10px 14px;cursor:pointer;white-space:nowrap}}button:disabled{{opacity:.55;cursor:wait}}.status{{margin:20px 0;padding:14px 16px;border-left:4px solid var(--accent);background:var(--panel)}}.status.complete{{border-color:var(--ok)}}.status.failed{{border-color:var(--bad)}}details{{margin-top:8px}}pre{{max-height:22rem;overflow:auto;white-space:pre-wrap;font-size:.8rem}}footer{{margin-top:42px;color:var(--muted)}}@media(max-width:560px){{li{{grid-template-columns:1fr}}li span{{grid-column:1}}.action{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><main>
<header><h1>{html.escape(manifest.get("title") or "Control panel")}</h1>
<p>{html.escape(manifest["system_type"])} · {html.escape(manifest["host"])} · signed in as {html.escape(manifest["username"])}</p></header>
{status}<section><h2>Web services</h2><div class="grid">{service_cards}</div></section>
<section><h2>Access</h2><ul>{access_rows}</ul></section>{action}
<footer>Managed by infra-tools</footer></main></body></html>'''


class ControlPanelHandler(BaseHTTPRequestHandler):
    server_version = "infra-tools-control-panel/1"
    sys_version = ""
    state: ControlPanelState

    def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            self._send(HTTPStatus.OK, "ok\n", "text/plain")
            return
        if path != "/":
            self._send(HTTPStatus.NOT_FOUND, "Not found\n", "text/plain")
            return
        self._send(HTTPStatus.OK, render_page(self.state), "text/html")

    def do_POST(self) -> None:
        if urllib.parse.urlsplit(self.path).path != "/actions/t3-update":
            self._send(HTTPStatus.NOT_FOUND, "Not found\n", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= _MAX_REQUEST_BYTES:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Invalid request\n", "text/plain")
            return
        try:
            values = urllib.parse.parse_qs(
                self.rfile.read(length).decode("utf-8", errors="strict"),
                keep_blank_values=True,
                max_num_fields=8,
            )
        except (UnicodeDecodeError, ValueError):
            self._send(HTTPStatus.BAD_REQUEST, "Invalid request\n", "text/plain")
            return
        if not secrets.compare_digest(values.get("csrf", [""])[0], self.state.csrf_token):
            self._send(HTTPStatus.FORBIDDEN, "Invalid request\n", "text/plain")
            return
        if not self.state.trigger_t3_update():
            self._send(HTTPStatus.CONFLICT, "Action is unavailable\n", "text/plain")
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def log_message(self, format_string: str, *args: object) -> None:
        return


class _ThreadingUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _ThreadingTCPHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the infra-tools control panel")
    parser.add_argument("--config", required=True)
    listener = parser.add_mutually_exclusive_group(required=True)
    listener.add_argument("--socket")
    listener.add_argument("--listen", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    state = ControlPanelState(_load_manifest(args.config))
    ControlPanelHandler.state = state
    if args.socket:
        if os.path.lexists(args.socket):
            if os.path.islink(args.socket) or not os.path.exists(args.socket):
                raise RuntimeError(f"Refusing unsafe control-panel socket: {args.socket}")
            os.unlink(args.socket)
        server: socketserver.BaseServer = _ThreadingUnixHTTPServer(
            args.socket, ControlPanelHandler
        )
        os.chmod(args.socket, 0o660)
    else:
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        server = _ThreadingTCPHTTPServer((args.listen, args.port), ControlPanelHandler)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        if args.socket:
            try:
                os.unlink(args.socket)
            except FileNotFoundError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
