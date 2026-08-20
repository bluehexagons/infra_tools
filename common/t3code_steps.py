"""Explicit T3 Code desktop and headless web-interface setup steps."""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import re
import shlex

from common.common_steps import _run_as_login_user
from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run
from lib.validation import validate_filesystem_path, validate_network_ip_or_cidr


T3_SERVICE_NAME = "infra-tools-t3code"
T3_SERVICE_FILE = f"/etc/systemd/system/{T3_SERVICE_NAME}.service"
T3_UFW_RULE_COMMENT_PREFIX = "infra_tools T3 Code"
_UFW_NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.*)$")
_T3_RUNTIME_RELATIVE_PATH = (".local", "share", "infra-tools", "t3code")


def _user_home(config: SetupConfig) -> str:
    try:
        return pwd.getpwnam(config.username).pw_dir
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {config.username}") from exc


def _workspace(config: SetupConfig, home: str) -> str:
    path = config.agent_workspace or os.path.join(home, "repos")
    validate_filesystem_path(path, must_exist=False)
    return path


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ufw_numbered_rules() -> list[tuple[int, str, str]]:
    """Return numbered UFW rules as ``(number, comment, line)`` records."""

    result = run("ufw status numbered", check=False, capture_output=True)
    if result.returncode != 0 or not isinstance(result.stdout, str):
        raise RuntimeError("Could not inspect UFW rules for T3 Code")
    rules: list[tuple[int, str, str]] = []
    for line in result.stdout.splitlines():
        match = _UFW_NUMBERED_RULE_RE.match(line.strip())
        if not match:
            continue
        comment = line.split("#", 1)[1].strip() if "#" in line else ""
        rules.append((int(match.group(1)), comment, line))
    return rules


def _remove_managed_rules(
    rules: list[tuple[int, str, str]],
    desired_comments: set[str],
) -> None:
    stale_numbers = [
        number
        for number, comment, _line in rules
        if comment.startswith(T3_UFW_RULE_COMMENT_PREFIX)
        and comment not in desired_comments
    ]
    for number in sorted(stale_numbers, reverse=True):
        result = run(f"ufw --force delete {number}", check=False)
        if result.returncode != 0:
            raise RuntimeError("Could not remove a stale T3 Code firewall rule")


def _configure_firewall(config: SetupConfig, port: int, host: str) -> None:
    sources = [
        validate_network_ip_or_cidr(source, "T3 Code web source")
        for source in config.web_interface_sources or []
    ]

    active = run(
        "ufw status 2>/dev/null | grep -q 'Status: active'",
        check=False,
    ).returncode == 0
    if _is_loopback(host):
        if active:
            _remove_managed_rules(_ufw_numbered_rules(), set())
        return
    if not sources:
        raise RuntimeError(
            "A non-loopback T3 Code web bind requires --web-interface-source"
        )
    if not active:
        raise RuntimeError(
            "T3 Code web access outside loopback requires an active UFW firewall"
        )

    existing_rules = _ufw_numbered_rules()
    existing_managed_comments = {
        comment
        for _number, comment, _line in existing_rules
        if comment.startswith(T3_UFW_RULE_COMMENT_PREFIX)
    }
    conflicting = [
        line
        for _number, comment, line in existing_rules
        if f"{port}/tcp" in line
        and "ALLOW IN" in line
        and comment not in existing_managed_comments
    ]
    if conflicting:
        raise RuntimeError(
            f"Unmanaged UFW allow rules already expose T3 Code port {port}; "
            "remove them before using --web-interface-source"
        )

    desired_comments: set[str] = set()
    for source in sources:
        comment = f"{T3_UFW_RULE_COMMENT_PREFIX} {port}/tcp source {source}"
        desired_comments.add(comment)
        if comment in existing_managed_comments:
            continue
        result = run(
            "ufw allow from "
            f"{shlex.quote(source)} to any port {port} proto tcp "
            f"comment {shlex.quote(comment)}",
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not install T3 Code firewall rule for {source}")
    updated_rules = _ufw_numbered_rules()
    observed_comments = {comment for _number, comment, _line in updated_rules}
    missing = desired_comments - observed_comments
    if missing:
        raise RuntimeError(
            "UFW did not retain all requested T3 Code source rules: "
            + ", ".join(sorted(missing))
        )
    _remove_managed_rules(updated_rules, desired_comments)


def _t3_runtime_path(home: str) -> str:
    return os.path.join(home, *_T3_RUNTIME_RELATIVE_PATH)


def _ensure_t3_shell_path(home: str, uid: int, gid: int) -> None:
    """Make the installed T3 CLI available in target-user login shells."""

    bashrc = os.path.join(home, ".bashrc")
    path_line = (
        'export PATH="$HOME/.local/share/infra-tools/t3code/'
        'node_modules/.bin:$PATH"\n'
    )
    existing = ""
    if os.path.exists(bashrc):
        with open(bashrc, "r", encoding="utf-8") as file_obj:
            existing = file_obj.read()
    if path_line not in existing:
        with open(bashrc, "a", encoding="utf-8") as file_obj:
            if existing and not existing.endswith("\n"):
                file_obj.write("\n")
            file_obj.write("# infra-tools T3 Code runtime\n")
            file_obj.write(path_line)
    os.chown(bashrc, uid, gid)


def _install_t3_runtime(home: str, username: str, uid: int, gid: int) -> str:
    """Install T3 and its Linux native dependencies for the target user.

    T3 depends on node-pty, which may need to compile on Linux.  Keeping this
    install in a persistent target-user directory means service restarts do
    not depend on npx's temporary cache, npm's current script policy, or a
    network connection.
    """

    for name, package in (
        ("T3 Code native build tools", "build-essential"),
        ("T3 Code Python build support", "python3"),
    ):
        if not install_package(name, package, f"apt-get install -y -qq {package}"):
            raise RuntimeError(f"Could not install {package}, required by T3 Code")

    runtime = _t3_runtime_path(home)
    os.makedirs(runtime, mode=0o700, exist_ok=True)
    os.chmod(runtime, 0o700)
    os.chown(runtime, uid, gid)

    package_json = os.path.join(runtime, "package.json")
    if not os.path.exists(package_json):
        with open(package_json, "w", encoding="utf-8") as file_obj:
            json.dump(
                {
                    "name": "infra-tools-t3code-runtime",
                    "private": True,
                },
                file_obj,
            )
            file_obj.write("\n")
        os.chmod(package_json, 0o600)
        os.chown(package_json, uid, gid)

    t3_binary = os.path.join(runtime, "node_modules", ".bin", "t3")
    safe_runtime = shlex.quote(runtime)
    safe_binary = shlex.quote(t3_binary)
    result = _run_as_login_user(
        username,
        home,
        "export NVM_DIR=\"$HOME/.nvm\" && "
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
        'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH" && '
        f"cd {safe_runtime} && "
        "npm install --no-fund --no-audit --dangerously-allow-all-scripts "
        "t3@latest && "
        f"test -x {safe_binary}",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        detail = f": {details[-500:]}" if details else ""
        raise RuntimeError(f"T3 Code installation failed{detail}")

    _ensure_t3_shell_path(home, uid, gid)
    os.chown(runtime, uid, gid)
    print(f"  ✓ T3 Code runtime installed for {username}")
    return t3_binary


def _write_wrapper(
    path: str,
    home: str,
    workspace: str,
    t3_binary: str,
    host: str,
    port: int,
    command: str,
) -> None:
    content = (
        "#!/bin/bash\n"
        "set -eu\n"
        f"export HOME={shlex.quote(home)}\n"
        'export NVM_DIR="$HOME/.nvm"\n'
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
        'export PATH="$HOME/.local/share/infra-tools/t3code/node_modules/.bin:'
        '$HOME/.opencode/bin:$HOME/.local/bin:$PATH"\n'
        f"export T3CODE_HOST={shlex.quote(host)}\n"
        f"export T3CODE_PORT={port}\n"
        f"cd {shlex.quote(workspace)}\n"
        f"exec {shlex.quote(t3_binary)} {command}\n"
    )
    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write(content)
    os.chmod(path, 0o755)


def install_t3code_web(config: SetupConfig) -> None:
    """Install a boot-persistent T3 Code headless service for direct pairing."""

    if is_dry_run():
        print("  [DRY-RUN] Would install the T3 Code headless web service")
        return

    home = _user_home(config)
    account = pwd.getpwnam(config.username)
    host = config.web_interface_host or "127.0.0.1"
    port = config.web_interface_port
    workspace = _workspace(config, home)
    _configure_firewall(config, port, host)

    os.makedirs(workspace, mode=0o755, exist_ok=True)
    os.makedirs(os.path.join(home, ".local", "bin"), mode=0o755, exist_ok=True)
    t3_binary = _install_t3_runtime(
        home,
        config.username,
        account.pw_uid,
        account.pw_gid,
    )
    wrapper = os.path.join(home, ".local", "bin", "infra-tools-t3code-web")
    pair_wrapper = os.path.join(home, ".local", "bin", "t3code-pair")
    _write_wrapper(
        wrapper,
        home,
        workspace,
        t3_binary,
        host,
        port,
        f"serve --host {shlex.quote(host)} --port {port} --no-browser",
    )
    _write_wrapper(pair_wrapper, home, workspace, t3_binary, host, port, "pair")
    os.chown(wrapper, account.pw_uid, account.pw_gid)
    os.chown(pair_wrapper, account.pw_uid, account.pw_gid)
    os.chown(workspace, account.pw_uid, account.pw_gid)

    service_content = f"""[Unit]
Description=T3 Code headless agentic coding service
After=network-online.target
Wants=network-online.target
RequiresMountsFor={home}
RequiresMountsFor={workspace}

[Service]
Type=simple
User={config.username}
WorkingDirectory={workspace}
Environment=HOME={home}
ExecStart={wrapper}
Restart=on-failure
RestartSec=5
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    with open(T3_SERVICE_FILE, "w", encoding="utf-8") as file_obj:
        file_obj.write(service_content)
    os.chmod(T3_SERVICE_FILE, 0o644)

    run("systemctl daemon-reload")
    run(f"systemctl enable {T3_SERVICE_NAME}.service")
    run(f"systemctl restart {T3_SERVICE_NAME}.service")
    print(f"  T3 Code web service listening on {host}:{port}")
    print("  Run 't3code-pair' as the target user to print a one-time pairing URL")


__all__ = ["install_t3code_web"]
