"""Provision isolated Playwright browser automation for coding agents."""

from __future__ import annotations

import json
import os
import shlex
from typing import cast

from lib.atomic_io import write_json_atomic, write_text_atomic
from lib.config import SetupConfig
from lib.remote_utils import is_dry_run, run
from lib.types import JSONDict

from .agent_steps import (
    _chown_path,
    _ensure_agent_directory,
    _reject_symlinked_agent_destination,
    _tool_available,
    _user_home,
)
from .common_steps import _run_as_login_user


PLAYWRIGHT_MCP_VERSION = "0.0.79"
PLAYWRIGHT_MCP_INTEGRITY = (
    "sha512-VpqD4a3vFyGQMY9sh3UJiO6wjcurggkljKfAyCHL0QWGY5m6Ehr3MNsAAHPDHO//"
    "n13g0PCjpHatAOiulrqdZQ=="
)
PLAYWRIGHT_VERSION = "1.63.0-alpha-2026-08-05"
PLAYWRIGHT_INTEGRITY = (
    "sha512-zbGZUK+JYkoDV3cUgfvh2czTBJL34Gmz5gHVI25xiIpvYSR17Q1M7TS8hnwECUe+"
    "IkKaeXbKrSyJTyogm2DVWw=="
)
PLAYWRIGHT_CORE_INTEGRITY = (
    "sha512-YussvUybTfBtyYbGXWh43f+5kNP03wg98M6mu4DphYET7PSbNVajsdLGjWE1xrsj"
    "qOw32i2wFlRP7U5mcOpMZg=="
)

PLAYWRIGHT_ROOT = "/opt/infra-tools-playwright"
PLAYWRIGHT_MCP_CLI = os.path.join(
    PLAYWRIGHT_ROOT,
    "node_modules",
    "@playwright",
    "mcp",
    "cli.js",
)
PLAYWRIGHT_CLI = os.path.join(
    PLAYWRIGHT_ROOT,
    "node_modules",
    "playwright",
    "cli.js",
)
PLAYWRIGHT_SMOKE_SCRIPT = os.path.join(PLAYWRIGHT_ROOT, "browser-smoke.js")
PLAYWRIGHT_MCP_WRAPPER = "/usr/local/bin/infra-tools-playwright-mcp"
PLAYWRIGHT_DOCTOR_WRAPPER = "/usr/local/bin/infra-tools-playwright-doctor"
SYSTEM_NODE = "/usr/bin/node"


_MCP_WRAPPER_CONTENT = f"""#!/bin/sh
set -eu
export PLAYWRIGHT_BROWSERS_PATH="${{PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}}"
exec {SYSTEM_NODE} {PLAYWRIGHT_MCP_CLI} --headless --isolated "$@"
"""

_DOCTOR_WRAPPER_CONTENT = f"""#!/bin/sh
set -eu
export PLAYWRIGHT_BROWSERS_PATH="${{PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}}"
exec {SYSTEM_NODE} {PLAYWRIGHT_SMOKE_SCRIPT}
"""

_SMOKE_SCRIPT_CONTENT = f"""'use strict';

const {{ chromium }} = require('{PLAYWRIGHT_ROOT}/node_modules/playwright');

(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  try {{
    const page = await browser.newPage();
    await page.setContent(`
      <button id="verify" onclick="this.textContent='browser-ready'">verify</button>
    `);
    await page.locator('#verify').click();
    const text = await page.locator('#verify').textContent();
    const screenshot = await page.screenshot();
    if (text !== 'browser-ready' || screenshot.length < 100) {{
      throw new Error('browser interaction or rendering verification failed');
    }}
    process.stdout.write('browser-ready\\n');
  }} finally {{
    await browser.close();
  }}
}})().catch((error) => {{
  process.stderr.write(`${{error.stack || error}}\\n`);
  process.exitCode = 1;
}});
"""


def _ensure_safe_root_path(path: str) -> None:
    """Reject a symlinked root-owned install path before mutation."""
    absolute_path = os.path.abspath(path)
    current = os.path.sep
    for component in absolute_path.split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise RuntimeError(f"Refusing symlinked browser automation path: {current}")


def _install_runtime_package() -> None:
    """Install and verify the pinned MCP package without lifecycle scripts."""
    _ensure_safe_root_path(PLAYWRIGHT_ROOT)
    run("apt-get -o DPkg::Lock::Timeout=60 install -y -qq ca-certificates nodejs npm")
    run(f"install -d -m 0755 -o root -g root {shlex.quote(PLAYWRIGHT_ROOT)}")
    run(
        "npm install --ignore-scripts --no-audit --no-fund --save-exact "
        f"--prefix {shlex.quote(PLAYWRIGHT_ROOT)} "
        f"@playwright/mcp@{PLAYWRIGHT_MCP_VERSION}"
    )

    node_result = run(f"{SYSTEM_NODE} --version", capture_output=True)
    raw_node_version = node_result.stdout.strip().removeprefix("v")
    try:
        node_major = int(raw_node_version.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"Could not determine Node.js version: {raw_node_version}") from exc
    if node_major < 18:
        raise RuntimeError("Playwright MCP requires Node.js 18 or newer")

    _verify_runtime_package(
        os.path.join(
            PLAYWRIGHT_ROOT,
            "node_modules",
            "@playwright",
            "mcp",
            "package.json",
        ),
        os.path.join(PLAYWRIGHT_ROOT, "package-lock.json"),
    )

    run(f"chown -R root:root {shlex.quote(PLAYWRIGHT_ROOT)}")
    run(f"chmod -R go-w {shlex.quote(PLAYWRIGHT_ROOT)}")


def _verify_runtime_package(package_path: str, lock_path: str) -> None:
    """Verify every npm package whose code is executed during provisioning."""
    expected_lock_entries = {
        "node_modules/@playwright/mcp": (
            PLAYWRIGHT_MCP_VERSION,
            PLAYWRIGHT_MCP_INTEGRITY,
        ),
        "node_modules/playwright": (PLAYWRIGHT_VERSION, PLAYWRIGHT_INTEGRITY),
        "node_modules/playwright-core": (
            PLAYWRIGHT_VERSION,
            PLAYWRIGHT_CORE_INTEGRITY,
        ),
    }
    try:
        with open(package_path, encoding="utf-8") as file_obj:
            package = json.load(file_obj)
        with open(lock_path, encoding="utf-8") as file_obj:
            package_lock = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not verify the installed Playwright MCP package") from exc

    if not isinstance(package, dict) or package.get("version") != PLAYWRIGHT_MCP_VERSION:
        raise RuntimeError("Installed Playwright MCP package failed version verification")
    lock_packages = package_lock.get("packages") if isinstance(package_lock, dict) else None
    if not isinstance(lock_packages, dict):
        raise RuntimeError("Installed Playwright package lock has no package inventory")

    for package_name, (expected_version, expected_integrity) in expected_lock_entries.items():
        lock_entry = lock_packages.get(package_name)
        if (
            not isinstance(lock_entry, dict)
            or lock_entry.get("version") != expected_version
            or lock_entry.get("integrity") != expected_integrity
        ):
            raise RuntimeError(
                f"Installed Playwright package failed integrity verification: {package_name}"
            )


def _write_launchers() -> None:
    """Install fixed headless launchers and the local browser smoke test."""
    for path in (
        PLAYWRIGHT_MCP_WRAPPER,
        PLAYWRIGHT_DOCTOR_WRAPPER,
        PLAYWRIGHT_SMOKE_SCRIPT,
    ):
        _ensure_safe_root_path(path)

    write_text_atomic(PLAYWRIGHT_MCP_WRAPPER, _MCP_WRAPPER_CONTENT, mode=0o755)
    write_text_atomic(PLAYWRIGHT_DOCTOR_WRAPPER, _DOCTOR_WRAPPER_CONTENT, mode=0o755)
    write_text_atomic(PLAYWRIGHT_SMOKE_SCRIPT, _SMOKE_SCRIPT_CONTENT, mode=0o644)


def _install_browser(config: SetupConfig) -> None:
    """Install OS dependencies and a user-owned Chromium browser payload."""
    user_home = _user_home(config)
    run(f"{SYSTEM_NODE} {shlex.quote(PLAYWRIGHT_CLI)} install-deps chromium")
    _run_as_login_user(
        config.username,
        user_home,
        "export PLAYWRIGHT_BROWSERS_PATH=\"$HOME/.cache/ms-playwright\" && "
        f"{SYSTEM_NODE} {shlex.quote(PLAYWRIGHT_CLI)} install chromium",
    )


def _configure_codex(config: SetupConfig) -> None:
    """Register the managed Playwright MCP launcher through the Codex CLI."""
    if not _tool_available(config, "codex"):
        raise RuntimeError("Codex was selected but is not available for MCP registration")
    user_home = _user_home(config)
    path_setup = 'export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH" && '
    _run_as_login_user(
        config.username,
        user_home,
        f"{path_setup}codex mcp add playwright -- {PLAYWRIGHT_MCP_WRAPPER}",
    )


def _configure_opencode(config: SetupConfig) -> None:
    """Merge the managed local MCP server into stable OpenCode configuration."""
    if not _tool_available(config, "opencode"):
        raise RuntimeError("OpenCode was selected but is not available for MCP registration")
    user_home = _user_home(config)
    config_dir = os.path.join(user_home, ".config", "opencode")
    config_path = os.path.join(config_dir, "opencode.json")
    _ensure_agent_directory(config_dir)
    _reject_symlinked_agent_destination(config_dir)

    value: JSONDict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as file_obj:
                loaded = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot update malformed OpenCode config: {config_path}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"OpenCode config must contain a JSON object: {config_path}")
        value = cast(JSONDict, loaded)

    existing_mcp = value.get("mcp")
    if existing_mcp is None:
        mcp: JSONDict = {}
    elif isinstance(existing_mcp, dict):
        mcp = cast(JSONDict, existing_mcp)
    else:
        raise RuntimeError("OpenCode config 'mcp' entry must contain a JSON object")
    mcp["playwright"] = {
        "type": "local",
        "command": [PLAYWRIGHT_MCP_WRAPPER],
        "enabled": True,
    }
    value["mcp"] = mcp
    write_json_atomic(config_path, value, mode=0o600, sort_keys=True)
    _chown_path(config, config_dir)


def _run_smoke_test(config: SetupConfig) -> None:
    """Verify browser startup, DOM interaction, rendering, and clean shutdown."""
    result = _run_as_login_user(
        config.username,
        _user_home(config),
        PLAYWRIGHT_DOCTOR_WRAPPER,
        capture_output=True,
    )
    if result.stdout.strip() != "browser-ready":
        raise RuntimeError("Playwright browser smoke test did not return browser-ready")
    print("  Playwright browser smoke test passed")


def install_browser_automation(config: SetupConfig) -> None:
    """Install Playwright and register it for each selected compatible agent."""
    if config.browser_automation != "playwright":
        raise RuntimeError(f"Unsupported browser automation provider: {config.browser_automation}")
    if is_dry_run():
        print("  [DRY-RUN] Would install pinned Playwright MCP and Chromium")
        print("  [DRY-RUN] Would register browser automation for selected agents")
        return

    _install_runtime_package()
    _write_launchers()
    _install_browser(config)

    selected_tools = set(config.selected_agent_tools())
    if "codex" in selected_tools:
        _configure_codex(config)
    if "opencode" in selected_tools:
        _configure_opencode(config)
    _run_smoke_test(config)
