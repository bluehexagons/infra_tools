#!/usr/bin/env python3
"""Serve the authenticated infra-tools web panel behind Nginx."""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


SOURCE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from common.t3code_steps import _temporary_t3_loginctl_shim


_MAX_CONFIG_BYTES = 256 * 1024
_MAX_REQUEST_BYTES = 16 * 1024
_MAX_OUTPUT_BYTES = 24 * 1024
_SYSTEM_OVERVIEW_CACHE_SECONDS = 30
_INTERNAL_WEB_URL_FILE = "/etc/infra-tools/internal-web/base-url"
_T3_UPDATE_TIMEOUT_SECONDS = 30 * 60
_T3_CORE_READINESS_CHECKS = (
    "service_active",
    "service_enabled",
    "runtime",
    "native_runtime",
    "wrapper",
    "pairing_helper",
    "endpoint",
    "t3_agent_skill",
)
_T3_GITHUB_READINESS_CHECKS = (
    "git_identity",
    "gh_authenticated",
    "git_credential_helper",
)
_T3_READINESS_LABELS = {
    "service_active": "service active",
    "service_enabled": "service enabled at boot",
    "runtime": "T3 runtime installed",
    "native_runtime": "native runtime ready",
    "wrapper": "pairing provider installed",
    "pairing_helper": "pairing helper installed",
    "endpoint": "web endpoint responding",
    "t3_agent_skill": "managed T3 skills installed",
    "git_identity": "Git author identity configured",
    "gh_authenticated": "GitHub CLI authenticated",
    "git_credential_helper": "Git credential helper configured",
}
_T3_UPDATE_SCRIPT = r'''
set -eu
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then . "$NVM_DIR/nvm.sh"; fi
export PATH="$INFRA_TOOLS_T3_LOGINCTL_SHIM:$HOME/.local/share/infra-tools/t3-npm/bin:$PATH"
unset INFRA_TOOLS_T3_LOGINCTL_SHIM
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
        raise RuntimeError(f"Web panel manifest must be a regular file: {path}")
    if os.path.getsize(path) > _MAX_CONFIG_BYTES:
        raise RuntimeError("Web panel manifest exceeds the size limit")
    with open(path, encoding="utf-8") as file_obj:
        value = json.load(file_obj)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("Invalid web panel manifest")
    for name in ("host", "system_type", "username"):
        if not isinstance(value.get(name), str) or not value[name]:
            raise RuntimeError(f"Web panel manifest has no valid {name}")
    for name in ("services", "access"):
        if not isinstance(value.get(name), list):
            raise RuntimeError(f"Web panel manifest has no valid {name}")
    if not isinstance(value.get("features"), dict):
        raise RuntimeError("Web panel manifest has no valid features")
    for name in ("t3_github_readiness", "t3_git_identity_readiness"):
        if not isinstance(value["features"].get(name, False), bool):
            raise RuntimeError("Web panel manifest has invalid T3 readiness settings")
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


def _internal_web_landing_service(
    utility: str,
    *,
    url_file: str = _INTERNAL_WEB_URL_FILE,
) -> dict[str, str] | None:
    """Return the shared web-hosting landing page when it is installed."""

    if not utility or os.path.islink(url_file) or not os.path.isfile(url_file):
        return None
    try:
        if os.path.getsize(url_file) > 2048:
            return None
        with open(url_file, encoding="utf-8") as file_obj:
            value = file_obj.read().strip().rstrip("/") + "/"
    except OSError:
        return None
    url = _safe_url(value)
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.path != "/"
        or parsed.query
        or parsed.fragment
    ):
        return None
    return {
        "label": "Web hosting",
        "url": url,
        "description": "Published sites, previews, and certificate trust",
    }


def discover_infra_web_services() -> list[dict[str, str]]:
    """Return live routes owned by the web panel service user."""

    utility = shutil.which("infra-web")
    if not utility:
        return []
    services: list[dict[str, str]] = []
    landing = _internal_web_landing_service(utility)
    if landing:
        services.append(landing)
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


def discover_certificate_trust() -> dict[str, str | bool] | None:
    """Return safe trust metadata for the shared internal-web certificate."""

    utility = shutil.which("infra-web")
    if not utility:
        return None
    payload = _run_json([utility, "ca", "--json"])
    if payload.get("publicly_trusted") is True:
        return {"publicly_trusted": True}
    url = _safe_url(payload.get("url"))
    fingerprint = payload.get("sha256")
    parsed = urllib.parse.urlsplit(url) if url else None
    if (
        not url
        or parsed is None
        or parsed.scheme != "https"
        or parsed.path != "/infra-tools-ca.crt"
        or parsed.query
        or parsed.fragment
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in fingerprint)
    ):
        return None
    return {
        "publicly_trusted": False,
        "url": url,
        "sha256": fingerprint.lower(),
    }


def _read_proc_values(path: str) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as file_obj:
            for line in file_obj:
                name, separator, raw_value = line.partition(":")
                if not separator:
                    continue
                fields = raw_value.split()
                if fields and fields[0].isdigit():
                    values[name] = int(fields[0]) * 1024
    except OSError:
        return {}
    return values


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or suffix == "TiB":
            precision = 0 if suffix in {"B", "KiB", "MiB"} else 1
            return f"{size:.{precision}f} {suffix}"
        size /= 1024
    return "0 B"


def _format_uptime(seconds: float) -> str:
    total_minutes = max(0, int(seconds // 60))
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _timer_properties(unit: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                unit,
                "--property=LoadState",
                "--property=ActiveState",
                "--property=NextElapseUSecRealtime",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    properties: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        name, separator, value = line.partition("=")
        if separator:
            properties[name] = value
    return properties


def collect_system_overview() -> list[dict[str, str]]:
    """Collect a small, non-sensitive live host report for the dashboard."""

    try:
        with open("/proc/uptime", encoding="utf-8") as file_obj:
            uptime = _format_uptime(float(file_obj.read(128).split()[0]))
    except (OSError, ValueError, IndexError):
        uptime = "Unavailable"

    memory = _read_proc_values("/proc/meminfo")
    memory_total = memory.get("MemTotal", 0)
    memory_available = memory.get("MemAvailable", 0)
    if memory_total:
        memory_used = max(0, memory_total - memory_available)
        memory_percent = round(memory_used * 100 / memory_total)
        memory_value = f"{memory_percent}% used"
        memory_description = (
            f"{_format_bytes(memory_available)} available of "
            f"{_format_bytes(memory_total)}"
        )
    else:
        memory_value = "Unavailable"
        memory_description = "Memory information could not be read"

    try:
        disk = shutil.disk_usage("/")
        disk_percent = round(disk.used * 100 / disk.total) if disk.total else 0
        disk_value = f"{disk_percent}% used"
        disk_description = (
            f"{_format_bytes(disk.free)} free of {_format_bytes(disk.total)}"
        )
    except OSError:
        disk_value = "Unavailable"
        disk_description = "Root filesystem usage could not be read"

    timer = _timer_properties("auto-update-apt.timer")
    if timer.get("LoadState") == "loaded" and timer.get("ActiveState") == "active":
        next_run = timer.get("NextElapseUSecRealtime")
        update_description = (
            f"Automatic package updates; next run {next_run}"
            if next_run and next_run != "n/a"
            else "Automatic package updates are scheduled"
        )
    elif timer.get("LoadState") == "loaded":
        update_description = "Automatic package update timer needs attention"
    else:
        update_description = "Automatic package updates are not configured"
    reboot_required = os.path.exists("/var/run/reboot-required")

    return [
        {"label": "Uptime", "value": uptime, "description": "Since the last boot"},
        {
            "label": "Memory",
            "value": memory_value,
            "description": memory_description,
        },
        {
            "label": "Root disk",
            "value": disk_value,
            "description": disk_description,
        },
        {
            "label": "Maintenance",
            "value": "Reboot required" if reboot_required else "No reboot pending",
            "description": update_description,
        },
    ]


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


def _evaluate_t3_readiness(
    manifest: dict[str, Any], output: str
) -> tuple[bool, str] | None:
    """Evaluate doctor JSON against the capabilities selected during setup."""

    try:
        records = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(records, list):
        return None
    result = next(
        (
            record
            for record in records
            if isinstance(record, dict) and record.get("capability") == "t3code"
        ),
        None,
    )
    if not isinstance(result, dict) or not isinstance(result.get("checks"), dict):
        return None

    checks = result["checks"]
    required = list(_T3_CORE_READINESS_CHECKS)
    if manifest["features"].get("t3_git_identity_readiness") is True:
        required.append("git_identity")
    if manifest["features"].get("t3_github_readiness") is True:
        required.extend(("gh_authenticated", "git_credential_helper"))
    failed = [name for name in required if checks.get(name) is not True]
    optional_failed = [
        name
        for name in _T3_GITHUB_READINESS_CHECKS
        if name not in required and checks.get(name) is False
    ]

    lines = ["Readiness checks:"]
    for name in required:
        marker = "✓" if checks.get(name) is True else "✗"
        lines.append(f"  {marker} {_T3_READINESS_LABELS[name]}")
    if optional_failed:
        labels = ", ".join(_T3_READINESS_LABELS[name] for name in optional_failed)
        lines.append(f"  • Not required by this setup: {labels}")
    fixes = result.get("fixes")
    if isinstance(fixes, list):
        for fix in fixes:
            if isinstance(fix, str) and fix:
                lines.append(f"  ✓ Repair applied: {fix}")
    return not failed, "\n".join(lines) + "\n"


class WebPanelState:
    """In-memory state for bounded maintenance actions."""

    def __init__(self, manifest: dict[str, Any]) -> None:
        self.manifest = manifest
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self.action_status = "idle"
        self.action_message = ""
        self.action_output = ""
        self._overview: list[dict[str, str]] = []
        self._overview_at = 0.0

    def system_overview(self) -> list[dict[str, str]]:
        """Return a briefly cached host report to keep refreshes inexpensive."""

        now = time.monotonic()
        with self._lock:
            if self._overview and now - self._overview_at < _SYSTEM_OVERVIEW_CACHE_SECONDS:
                return list(self._overview)
        overview = collect_system_overview()
        with self._lock:
            self._overview = overview
            self._overview_at = now
            return list(self._overview)

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
        threading.Thread(target=self._run_t3_update_guarded, daemon=True).start()
        return True

    def _run_t3_update_guarded(self) -> None:
        try:
            self._run_t3_update()
        except Exception as exc:
            self._finish_action(
                "failed",
                "T3 Code update stopped unexpectedly.",
                f"{type(exc).__name__}: {exc}",
            )

    def _run_t3_update(self) -> None:
        home = os.path.expanduser("~")
        environment = os.environ.copy()
        environment.pop("INFRA_TOOLS_T3_LOGINCTL_SHIM", None)
        environment["HOME"] = home
        environment["PATH"] = os.pathsep.join(
            (
                os.path.join(home, ".local", "bin"),
                os.path.join(home, ".local", "share", "infra-tools", "t3-npm", "bin"),
                environment.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            )
        )
        environment.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        environment.setdefault(
            "DBUS_SESSION_BUS_ADDRESS",
            f"unix:path=/run/user/{os.getuid()}/bus",
        )
        try:
            with _temporary_t3_loginctl_shim(
                home, self.manifest["username"]
            ) as shim_path:
                update_environment = environment.copy()
                update_environment["INFRA_TOOLS_T3_LOGINCTL_SHIM"] = shim_path
                update_environment["PATH"] = os.pathsep.join(
                    (shim_path, environment["PATH"])
                )
                result = subprocess.run(
                    ["/bin/bash", "-lc", _T3_UPDATE_SCRIPT],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_T3_UPDATE_TIMEOUT_SECONDS,
                    cwd=home,
                    env=update_environment,
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

        doctor = shutil.which("infra-tools", path=environment["PATH"])
        if not doctor:
            self._finish_action(
                "failed",
                "T3 Code updated, but the managed readiness command is unavailable.",
                output,
            )
            return
        try:
            check = subprocess.run(
                [
                    doctor,
                    "agent",
                    "doctor",
                    "--capability",
                    "t3code",
                    "--fix",
                    "--json",
                ],
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
        readiness = _evaluate_t3_readiness(self.manifest, check.stdout or "")
        if readiness is None:
            output += (check.stdout or "") + (check.stderr or "")
            self._finish_action(
                "failed",
                "T3 Code updated, but its readiness result was invalid.",
                output,
            )
            return
        ready, readiness_output = readiness
        output += (check.stderr or "") + readiness_output
        if not ready:
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


_PAGE_STYLE = """
:root {
  --bg: #f4f6f8;
  --panel: #fff;
  --text: #17202a;
  --muted: #667085;
  --line: #dce2e8;
  --accent: #2457c5;
  --accent-soft: #eaf0ff;
  --ok: #167044;
  --bad: #b32929;
  --shadow: 0 12px 36px rgb(18 32 52 / 7%);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101419;
    --panel: #181e25;
    --text: #eef2f6;
    --muted: #a5afbd;
    --line: #303945;
    --accent: #91adff;
    --accent-soft: #202c49;
    --ok: #76d69d;
    --bad: #ff9b9b;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 system-ui, sans-serif;
}
main { max-width: 920px; margin: auto; padding: 44px 20px 64px; }
header { margin-bottom: 36px; }
.eyebrow, .section-kicker {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: .75rem;
  font-weight: 750;
  letter-spacing: .11em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  font-size: clamp(2rem, 6vw, 3.25rem);
  letter-spacing: -.045em;
  line-height: 1.06;
}
.lede { max-width: 620px; margin: 12px 0 0; color: var(--muted); }
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 22px 0 0;
}
.meta div {
  display: flex;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
}
.meta dt { color: var(--muted); }
.meta dd { margin: 0; font-weight: 650; }
section { margin-top: 36px; }
.section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 13px;
}
h2 { margin: 0; font-size: 1.2rem; letter-spacing: -.015em; }
.count { color: var(--muted); font-size: .85rem; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 11px;
}
.card {
  display: flex;
  min-height: 132px;
  flex-direction: column;
  gap: 5px;
  padding: 17px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow);
  color: var(--text);
  text-decoration: none;
}
.card:hover { border-color: var(--accent); }
.card:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 3px;
}
.card-description { color: var(--muted); font-size: .9rem; }
.card-url {
  margin-top: auto;
  color: var(--accent);
  font-size: .8rem;
  overflow-wrap: anywhere;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 11px;
  margin: 0;
}
.metric {
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.metric dt { color: var(--muted); font-size: .82rem; }
.metric dd { margin: 5px 0 0; }
.metric-value { display: block; font-size: 1.15rem; font-weight: 750; }
.metric-description { display: block; margin-top: 4px; color: var(--muted); font-size: .82rem; }
.trust-panel {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.trust-panel > p { margin: 5px 0 0; color: var(--muted); }
.trust-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 15px; }
.trust-download {
  display: inline-block;
  padding: 9px 13px;
  border-radius: 9px;
  background: var(--accent);
  color: var(--panel);
  font-weight: 750;
  text-decoration: none;
}
.fingerprint { display: block; margin-top: 13px; overflow-wrap: anywhere; }
.trust-steps { margin: 10px 0 0; padding-left: 22px; }
.trust-steps li { margin-top: 8px; }
.access-list {
  list-style: none;
  padding: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.access-list li {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr);
  gap: 4px 18px;
  padding: 14px 17px;
  border-bottom: 1px solid var(--line);
}
.access-list li:last-child { border: 0; }
.access-list span { grid-column: 2; color: var(--muted); font-size: .88rem; }
code { overflow-wrap: anywhere; }
.empty {
  margin: 0;
  padding: 18px;
  border: 1px dashed var(--line);
  border-radius: 12px;
  color: var(--muted);
}
.action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.action p { max-width: 590px; margin: 4px 0 0; color: var(--muted); }
button {
  border: 0;
  border-radius: 9px;
  background: var(--accent);
  color: var(--panel);
  font: inherit;
  font-weight: 750;
  padding: 10px 14px;
  cursor: pointer;
  white-space: nowrap;
}
button:disabled { opacity: .58; cursor: wait; }
.status {
  margin: 0 0 30px;
  padding: 15px 17px;
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  background: var(--panel);
}
.status.complete { border-left-color: var(--ok); }
.status.failed { border-left-color: var(--bad); }
.status p { margin: 2px 0 0; }
details { margin-top: 10px; }
summary { width: max-content; cursor: pointer; color: var(--accent); }
pre {
  max-height: 22rem;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg);
  white-space: pre-wrap;
  font-size: .8rem;
}
footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 48px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: .85rem;
}
@media (max-width: 560px) {
  main { padding-top: 30px; }
  .access-list li { grid-template-columns: 1fr; }
  .access-list span { grid-column: 1; }
  .action { align-items: stretch; flex-direction: column; }
  button { width: 100%; }
  footer { flex-direction: column; }
}
""".strip()


def _system_type_label(value: str) -> str:
    words = value.replace("_", " ").replace("-", " ").split()
    return " ".join("VM" if word.lower() == "vm" else word.capitalize() for word in words)


def render_page(state: WebPanelState) -> str:
    """Render a small no-JavaScript dashboard from current capability state."""

    manifest = state.manifest
    services = _deduplicate_services(
        manifest["services"], discover_infra_web_services()
    )
    service_cards = "".join(
        (
            '<a class="card" href="{}"><strong>{}</strong>'
            '<span class="card-description">{}</span>'
            '<span class="card-url">{} &#8599;</span></a>'
        ).format(
            html.escape(record["url"], quote=True),
            html.escape(record["label"]),
            html.escape(record["description"] or "Open this service"),
            html.escape(record["url"]),
        )
        for record in services
    ) or '<p class="empty">No hosted web services are available on this machine.</p>'

    access_rows = "".join(
        "<li><strong>{}</strong><code>{}</code><span>{}</span></li>".format(
            html.escape(str(record.get("label", "Access"))),
            html.escape(str(record.get("value", ""))),
            html.escape(str(record.get("description", ""))),
        )
        for record in manifest["access"]
        if isinstance(record, dict) and record.get("value")
    )
    access_content = (
        f'<ul class="access-list">{access_rows}</ul>'
        if access_rows
        else '<p class="empty">No additional access methods are configured.</p>'
    )

    overview = state.system_overview()
    overview_cards = "".join(
        '<div class="metric"><dt>{}</dt><dd><span class="metric-value">{}</span>'
        '<span class="metric-description">{}</span></dd></div>'.format(
            html.escape(record["label"]),
            html.escape(record["value"]),
            html.escape(record["description"]),
        )
        for record in overview
    )

    trust = discover_certificate_trust()
    trust_section = ""
    if trust and trust.get("publicly_trusted") is True:
        trust_section = '''<section aria-labelledby="trust-heading">
<div class="section-heading"><div><p class="section-kicker">Secure connection</p>
<h2 id="trust-heading">Certificate trust</h2></div></div>
<div class="trust-panel"><strong>No certificate installation required</strong>
<p>The shared web-hosting certificate is issued by a publicly trusted authority.</p></div></section>'''
    elif trust:
        trust_url = html.escape(str(trust["url"]), quote=True)
        fingerprint = html.escape(str(trust["sha256"]))
        trust_section = f'''<section aria-labelledby="trust-heading">
<div class="section-heading"><div><p class="section-kicker">One-time setup</p>
<h2 id="trust-heading">Certificate trust</h2></div></div>
<div class="trust-panel"><strong>Trust this machine on another device</strong>
<p>Install this machine's public CA once to trust the web panel, hosted sites, and managed HTTPS services. Compare the fingerprint before installing it.</p>
<div class="trust-actions"><a class="trust-download" href="{trust_url}">Download VM CA certificate</a></div>
<code class="fingerprint">SHA-256 {fingerprint}</code>
<details><summary>Installation help</summary><ol class="trust-steps">
<li><strong>Verify first:</strong> run <code>sha256sum infra-tools-ca.crt</code> on Linux or <code>Get-FileHash .\\infra-tools-ca.crt -Algorithm SHA256</code> in PowerShell and compare it with the fingerprint above.</li>
<li><strong>If the download is blocked:</strong> copy <code>/srv/infra-tools/web/infra-tools-ca.crt</code> over SSH, then verify it the same way.</li>
<li><strong>Debian / Ubuntu:</strong> copy the verified certificate to <code>/usr/local/share/ca-certificates/infra-tools.crt</code>, then run <code>sudo update-ca-certificates</code>.</li>
<li><strong>Windows:</strong> run <code>certutil -user -addstore -f Root infra-tools-ca.crt</code>.</li>
<li><strong>ChromeOS:</strong> import it under Certificate Manager → Authorities and enable website trust.</li>
<li><strong>Android:</strong> use Security &amp; privacy → Install a certificate → CA certificate.</li>
</ol></details></div></section>'''

    action = ""
    if state.t3_update_available():
        running = state.action_status == "running"
        disabled = " disabled" if running else ""
        button_label = "Update in progress…" if running else "Update to latest"
        action = f'''<section aria-labelledby="maintenance-heading">
<div class="section-heading"><div><p class="section-kicker">Available action</p>
<h2 id="maintenance-heading">Maintenance</h2></div></div>
<div class="action"><div><strong>T3 Code</strong><p>Install the latest upstream release, then verify that the managed service is ready. This runs in the background.</p></div>
<form method="post" action="/actions/t3-update">
<input type="hidden" name="csrf" value="{html.escape(state.csrf_token, quote=True)}">
<button type="submit"{disabled}>{button_label}</button></form></div></section>'''

    status = ""
    if state.action_message:
        output = (
            f"<details><summary>View command output</summary><pre>{html.escape(state.action_output)}</pre></details>"
            if state.action_output
            else ""
        )
        role = "alert" if state.action_status == "failed" else "status"
        status = (
            f'<aside class="status {html.escape(state.action_status)}" role="{role}" '
            f'aria-live="polite"><strong>Maintenance status</strong>'
            f"<p>{html.escape(state.action_message)}</p>{output}</aside>"
        )

    title = html.escape(str(manifest.get("title") or "Managed machine"))
    host = html.escape(manifest["host"])
    username = html.escape(manifest["username"])
    system_type = html.escape(_system_type_label(manifest["system_type"]))
    refresh = (
        '<meta http-equiv="refresh" content="3">'
        if state.action_status == "running"
        else ""
    )
    service_count = f"{len(services)} service" + ("" if len(services) == 1 else "s")
    access_count = sum(
        1
        for record in manifest["access"]
        if isinstance(record, dict) and record.get("value")
    )
    access_label = f"{access_count} method" + ("" if access_count == 1 else "s")

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">{refresh}
<title>Web panel · {title}</title>
<style>{_PAGE_STYLE}</style></head><body><main>
<header><p class="eyebrow">infra-tools web panel</p><h1>{title}</h1>
<p class="lede">Services, connection details, and available maintenance for <code>{host}</code>.</p>
<dl class="meta"><div><dt>System</dt><dd>{system_type}</dd></div>
<div><dt>User</dt><dd>{username}</dd></div></dl></header>
{status}<section aria-labelledby="services-heading"><div class="section-heading"><div>
<p class="section-kicker">Open in browser</p><h2 id="services-heading">Web services</h2></div>
<span class="count">{service_count}</span></div><div class="grid">{service_cards}</div></section>
<section aria-labelledby="overview-heading"><div class="section-heading"><div>
<p class="section-kicker">Live snapshot</p><h2 id="overview-heading">System overview</h2></div>
<span class="count">Refreshed periodically</span></div>
<dl class="overview-grid">{overview_cards}</dl></section>
<section aria-labelledby="access-heading"><div class="section-heading"><div>
<p class="section-kicker">Connect directly</p><h2 id="access-heading">Access</h2></div>
<span class="count">{access_label}</span></div>{access_content}</section>{trust_section}{action}
<footer><span>Managed by infra-tools</span><span>Authenticated as {username}</span></footer>
</main></body></html>'''


class WebPanelHandler(BaseHTTPRequestHandler):
    server_version = "infra-tools-web-panel/1"
    sys_version = ""
    state: WebPanelState

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
    parser = argparse.ArgumentParser(description="Serve the infra-tools web panel")
    parser.add_argument("--config", required=True)
    listener = parser.add_mutually_exclusive_group(required=True)
    listener.add_argument("--socket")
    listener.add_argument("--listen", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    state = WebPanelState(_load_manifest(args.config))
    WebPanelHandler.state = state
    if args.socket:
        if os.path.lexists(args.socket):
            if os.path.islink(args.socket) or not os.path.exists(args.socket):
                raise RuntimeError(f"Refusing unsafe web panel socket: {args.socket}")
            os.unlink(args.socket)
        server: socketserver.BaseServer = _ThreadingUnixHTTPServer(
            args.socket, WebPanelHandler
        )
        os.chmod(args.socket, 0o660)
    else:
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        server = _ThreadingTCPHTTPServer((args.listen, args.port), WebPanelHandler)
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
