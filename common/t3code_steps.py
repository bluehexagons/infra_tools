"""Explicit T3 Code desktop and headless web-interface setup steps."""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import re
import shlex
import shutil
import stat
import tempfile
from typing import Sequence

from common.common_steps import _run_as_login_user
from lib.atomic_io import write_text_atomic
from lib.auth_failure_bans import (
    configure_nginx_auth_failure_ban,
    remove_nginx_auth_failure_ban,
)
from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run
from lib.validation import validate_filesystem_path, validate_network_ip_or_cidr
from lib.validators import validate_username


T3_SERVICE_NAME = "infra-tools-t3code"
T3_SERVICE_FILE = f"/etc/systemd/system/{T3_SERVICE_NAME}.service"
T3_CONNECT_RESTART_PATH_UNIT = f"{T3_SERVICE_NAME}-connect.path"
T3_CONNECT_RESTART_SERVICE_UNIT = f"{T3_SERVICE_NAME}-connect.service"
T3_CONNECT_RESTART_PATH_FILE = (
    f"/etc/systemd/system/{T3_CONNECT_RESTART_PATH_UNIT}"
)
T3_CONNECT_RESTART_SERVICE_FILE = (
    f"/etc/systemd/system/{T3_CONNECT_RESTART_SERVICE_UNIT}"
)
T3_UFW_RULE_COMMENT_PREFIX = "infra_tools T3 Code"
DEVICE_PAIRING_SERVICE_NAME = "infra-tools-device-pairing"
DEVICE_PAIRING_SERVICE_FILE = (
    f"/etc/systemd/system/{DEVICE_PAIRING_SERVICE_NAME}.service"
)
DEVICE_PAIRING_CONFIG_DIR = "/etc/infra-tools/device-pairing"
DEVICE_PAIRING_AUTH_FILE = f"{DEVICE_PAIRING_CONFIG_DIR}/htpasswd"
DEVICE_PAIRING_PROVIDERS_FILE = f"{DEVICE_PAIRING_CONFIG_DIR}/providers.json"
DEVICE_PAIRING_PAYLOAD_FILE = "/opt/infra_tools/device_pairing_payload/htpasswd"
DEVICE_PAIRING_SOCKET = "/run/infra-tools-device-pairing/http.sock"
DEVICE_PAIRING_SCRIPT = (
    "/opt/infra_tools/common/service_tools/device_pairing_service.py"
)
T3_ADMIN_PAIR_SCRIPT = (
    "/opt/infra_tools/common/service_tools/t3code_admin_pair.py"
)
T3_AGENT_SKILLS_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "agent_skills"
)
T3_AGENT_SKILL_NAME = "infra-tools-t3code"
DEVICE_PAIRING_NGINX_SITE = "/etc/nginx/sites-available/infra-tools-device-pairing"
DEVICE_PAIRING_NGINX_LINK = "/etc/nginx/sites-enabled/infra-tools-device-pairing"
DEVICE_PAIRING_AUTH_FAILURE_LOG = (
    "/var/log/nginx/infra-tools-device-pairing-auth-failures.log"
)
_UFW_NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.*)$")
_T3_RUNTIME_RELATIVE_PATH = (".local", "share", "infra-tools", "t3code")
# Keep the NVM path injected into the inherited PATH ahead of system Node while
# making system package locations deterministic for direct T3 child processes.
_T3_PATH_EXPORT = (
    'export PATH="$HOME/.local/share/infra-tools/t3code/node_modules/.bin:'
    '$HOME/.opencode/bin:$HOME/.local/bin:$PATH:'
    '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"'
)
_T3_GH_CONFIG_EXPORT = 'export GH_CONFIG_DIR="$HOME/.config/gh"'


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
        for source in config.effective_web_interface_sources()
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
            "A non-loopback T3 Code web bind requires --access-source or "
            "--web-interface-source"
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
    exposed_ports = [(port, "")]
    if config.device_pairing_providers:
        exposed_ports.append((config.device_pairing_port, " pairing"))
    conflicting = []
    for exposed_port, _suffix in exposed_ports:
        conflicting.extend(
            line
            for _number, comment, line in existing_rules
            if f"{exposed_port}/tcp" in line
            and "ALLOW IN" in line
            and comment not in existing_managed_comments
        )
    if conflicting:
        port_list = ", ".join(str(item[0]) for item in exposed_ports)
        raise RuntimeError(
            f"Unmanaged UFW allow rules already expose managed port(s) {port_list}; "
            "remove them before using --web-interface-source"
        )

    desired_comments: set[str] = set()
    for source in sources:
        for exposed_port, suffix in exposed_ports:
            comment = (
                f"{T3_UFW_RULE_COMMENT_PREFIX}{suffix} "
                f"{exposed_port}/tcp source {source}"
            )
            desired_comments.add(comment)
            if comment in existing_managed_comments:
                continue
            result = run(
                "ufw allow from "
                f"{shlex.quote(source)} to any port {exposed_port} proto tcp "
                f"comment {shlex.quote(comment)}",
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Could not install T3 Code firewall rule for {source}"
                )
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
    if os.path.lexists(bashrc) and (
        os.path.islink(bashrc) or not os.path.isfile(bashrc)
    ):
        raise RuntimeError(f"Refusing unsafe target shell configuration: {bashrc}")
    path_line = (
        'export PATH="$HOME/.local/share/infra-tools/t3code/'
        'node_modules/.bin:$PATH"\n'
    )
    existing = ""
    if os.path.exists(bashrc):
        with open(bashrc, "r", encoding="utf-8") as file_obj:
            existing = file_obj.read()
    if path_line not in existing:
        updated = existing
        if updated and not updated.endswith("\n"):
            updated += "\n"
        updated += "# infra-tools T3 Code runtime\n"
        updated += path_line
        mode = stat.S_IMODE(os.stat(bashrc).st_mode) if os.path.exists(bashrc) else 0o644
        write_text_atomic(bashrc, updated, mode=mode)
    os.chown(bashrc, uid, gid)


def _install_t3_runtime(
    home: str,
    username: str,
    uid: int,
    gid: int,
    *,
    refresh: bool = False,
) -> tuple[str, bool]:
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
    if os.path.lexists(runtime) and (
        os.path.islink(runtime) or not os.path.isdir(runtime)
    ):
        raise RuntimeError(f"Refusing unsafe T3 runtime directory: {runtime}")
    os.makedirs(runtime, mode=0o700, exist_ok=True)
    os.chmod(runtime, 0o700)
    os.chown(runtime, uid, gid)

    package_json = os.path.join(runtime, "package.json")
    if os.path.lexists(package_json) and (
        os.path.islink(package_json) or not os.path.isfile(package_json)
    ):
        raise RuntimeError(f"Refusing unsafe T3 runtime manifest: {package_json}")
    if not os.path.exists(package_json):
        write_text_atomic(
            package_json,
            json.dumps(
                {
                    "name": "infra-tools-t3code-runtime",
                    "private": True,
                }
            )
            + "\n",
            mode=0o600,
        )
        os.chown(package_json, uid, gid)

    t3_binary = os.path.join(runtime, "node_modules", ".bin", "t3")
    package_lock = os.path.join(runtime, "package-lock.json")
    runtime_ready = (
        not refresh
        and os.path.isfile(package_lock)
        and os.path.isfile(t3_binary)
    )
    runtime_repaired = False
    if runtime_ready:
        safe_runtime = shlex.quote(runtime)
        safe_binary = shlex.quote(t3_binary)
        health = _run_as_login_user(
            username,
            home,
            "export NVM_DIR=\"$HOME/.nvm\" && "
            '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
            f"{_T3_PATH_EXPORT} && "
            f"cd {safe_runtime} && test -x {safe_binary} && "
            "node -e 'require(\"node-pty\")' && "
            f"{safe_binary} --version >/dev/null 2>&1 && "
            f"{safe_binary} auth session issue --help >/dev/null 2>&1",
            check=False,
            capture_output=True,
        )
        runtime_ready = health.returncode == 0

    if not runtime_ready:
        safe_runtime = shlex.quote(runtime)
        safe_binary = shlex.quote(t3_binary)
        result = _run_as_login_user(
            username,
            home,
            "export NVM_DIR=\"$HOME/.nvm\" && "
            '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
            f"{_T3_PATH_EXPORT} && "
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
        runtime_repaired = True

    _ensure_t3_shell_path(home, uid, gid)
    os.chown(runtime, uid, gid)
    if runtime_repaired:
        print(f"  ✓ T3 Code runtime installed or repaired for {username}")
    else:
        print(f"  ✓ T3 Code runtime already healthy for {username}")
    return t3_binary, runtime_repaired


def _write_executable_if_changed(path: str, content: str) -> bool:
    """Atomically write a managed user executable without following symlinks."""

    if os.path.lexists(path) and (
        os.path.islink(path) or not os.path.isfile(path)
    ):
        raise RuntimeError(f"Refusing unsafe managed executable: {path}")
    changed = True
    try:
        with open(path, encoding="utf-8") as file_obj:
            changed = file_obj.read() != content
    except FileNotFoundError:
        pass
    if changed:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(path)}-", dir=os.path.dirname(path)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
                file_obj.write(content)
            os.chmod(temporary, 0o755)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    else:
        os.chmod(path, 0o755)
    return changed


def _write_wrapper(
    path: str,
    home: str,
    workspace: str,
    t3_binary: str,
    host: str,
    port: int,
    command: str,
) -> bool:
    content = (
        "#!/bin/bash\n"
        "set -eu\n"
        f"export HOME={shlex.quote(home)}\n"
        'export NVM_DIR="$HOME/.nvm"\n'
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
        f"{_T3_PATH_EXPORT}\n"
        f"{_T3_GH_CONFIG_EXPORT}\n"
        f"export T3CODE_HOST={shlex.quote(host)}\n"
        f"export T3CODE_PORT={port}\n"
        f"cd {shlex.quote(workspace)}\n"
        f"exec {shlex.quote(t3_binary)} {command}\n"
    )
    return _write_executable_if_changed(path, content)


def _write_passthrough_wrapper(path: str, home: str, t3_binary: str) -> bool:
    """Write a stable T3 launcher that accepts only caller-supplied argv."""

    content = (
        "#!/bin/bash\n"
        "set -eu\n"
        f"export HOME={shlex.quote(home)}\n"
        'export NVM_DIR="$HOME/.nvm"\n'
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
        f"{_T3_PATH_EXPORT}\n"
        f"{_T3_GH_CONFIG_EXPORT}\n"
        f'exec {shlex.quote(t3_binary)} "$@"\n'
    )
    return _write_executable_if_changed(path, content)


def _remove_legacy_t3_shim(home: str) -> bool:
    """Remove only the obsolete infra-tools T3 GitHub shim from old installs."""

    shim = os.path.join(_t3_runtime_path(home), "shims", "gh")
    if not os.path.isfile(shim) or os.path.islink(shim):
        return False
    try:
        with open(shim, encoding="utf-8") as file_obj:
            content = file_obj.read()
    except OSError:
        return False
    if "t3code_gh_shim.py" not in content:
        return False
    os.remove(shim)
    shim_dir = os.path.dirname(shim)
    try:
        os.rmdir(shim_dir)
    except OSError:
        pass
    return True


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _t3_pairing_urls(target_host: str, bind_host: str, port: int) -> tuple[str, str]:
    if bind_host == "0.0.0.0":
        local_host = "127.0.0.1"
        public_host = target_host
    elif bind_host in {"::", "[::]"}:
        local_host = "::1"
        public_host = target_host
    else:
        local_host = bind_host
        public_host = bind_host
    return (
        f"http://{_url_host(local_host)}:{port}",
        f"http://{_url_host(public_host)}:{port}",
    )


def _write_admin_pair_wrapper(
    path: str,
    home: str,
    workspace: str,
    t3_cli_wrapper: str,
    server_url: str,
    base_url: str,
) -> bool:
    content = (
        "#!/bin/bash\n"
        "set -eu\n"
        f"export HOME={shlex.quote(home)}\n"
        f"cd {shlex.quote(workspace)}\n"
        f"exec /usr/bin/python3 {shlex.quote(T3_ADMIN_PAIR_SCRIPT)} "
        f"--t3-binary {shlex.quote(t3_cli_wrapper)} "
        f"--base-dir {shlex.quote(os.path.join(home, '.t3'))} "
        f"--server-url {shlex.quote(server_url)} "
        f'--base-url {shlex.quote(base_url)} "$@"\n'
    )
    return _write_executable_if_changed(path, content)


def _write_text_if_changed(path: str, content: str, mode: int) -> bool:
    if os.path.islink(path):
        raise RuntimeError(f"Refusing symlinked managed configuration: {path}")
    try:
        with open(path, encoding="utf-8") as file_obj:
            changed = file_obj.read() != content
    except OSError:
        changed = True
    if changed:
        write_text_atomic(path, content, mode=mode)
    else:
        os.chmod(path, mode)
    return changed


def _ensure_t3_agent_skill(username: str, agent_tools: Sequence[str]) -> bool:
    """Install the managed T3 workflow skill for compatible terminal agents."""

    if not {"codex", "opencode"}.intersection(agent_tools):
        return False
    if not validate_username(username):
        raise ValueError(f"Invalid T3 Code agent-skill username: {username}")
    account = pwd.getpwnam(username)
    home = account.pw_dir
    validate_filesystem_path(home, must_exist=True)
    source = os.path.join(T3_AGENT_SKILLS_ROOT, T3_AGENT_SKILL_NAME, "SKILL.md")
    if os.path.islink(source) or not os.path.isfile(source):
        raise RuntimeError(f"Managed T3 Code agent skill is missing: {source}")
    skills_dir = os.path.join(home, ".agents", "skills", T3_AGENT_SKILL_NAME)
    parent = os.path.dirname(skills_dir)
    for directory in (os.path.dirname(parent), parent, skills_dir):
        if os.path.lexists(directory):
            if os.path.islink(directory) or not os.path.isdir(directory):
                raise RuntimeError(f"Refusing unsafe T3 Code skill directory: {directory}")
            if os.stat(directory).st_uid != account.pw_uid:
                raise RuntimeError(
                    f"Refusing T3 Code skill directory owned by another user: {directory}"
                )
        else:
            os.mkdir(directory, mode=0o755)
            os.chown(directory, account.pw_uid, account.pw_gid)
    destination = os.path.join(skills_dir, "SKILL.md")
    if os.path.islink(destination):
        raise RuntimeError(f"Refusing symlinked managed T3 Code skill: {destination}")
    with open(source, encoding="utf-8") as file_obj:
        content = file_obj.read()
    if os.path.exists(destination):
        with open(destination, encoding="utf-8") as file_obj:
            previous = file_obj.read()
        if "managed-by: infra_tools" not in previous:
            raise RuntimeError(f"Refusing to replace unmanaged T3 Code skill: {destination}")
    else:
        previous = None
    changed = previous != content
    if changed:
        write_text_atomic(destination, content, mode=0o644)
    os.chmod(destination, 0o644)
    os.chown(destination, account.pw_uid, account.pw_gid)
    return changed


def _validate_htpasswd_file(path: str) -> None:
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError(f"Device-pairing auth must be a regular file: {path}")
    if os.path.getsize(path) > 64 * 1024:
        raise RuntimeError("Device-pairing auth file exceeds the size limit")
    try:
        with open(path, encoding="utf-8") as file_obj:
            records = [
                line.rstrip("\n") for line in file_obj if line.rstrip("\n")
            ]
    except UnicodeDecodeError as exc:
        raise RuntimeError("Device-pairing auth file must be UTF-8 text") from exc
    if not records:
        raise RuntimeError("Device-pairing auth file has no user records")
    for record in records:
        username, separator, password_hash = record.partition(":")
        if (
            not separator
            or not validate_username(username)
            or not password_hash.startswith("$")
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in record
            )
        ):
            raise RuntimeError("Device-pairing auth file contains an invalid record")


def _replace_pairing_auth_file(payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=".htpasswd-", dir=DEVICE_PAIRING_CONFIG_DIR
    )
    try:
        with os.fdopen(descriptor, "wb") as file_obj:
            file_obj.write(payload)
        os.chmod(temporary, 0o640)
        os.replace(temporary, DEVICE_PAIRING_AUTH_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _install_pairing_auth_file() -> tuple[bool, bytes | None]:
    if os.path.lexists(DEVICE_PAIRING_CONFIG_DIR) and (
        os.path.islink(DEVICE_PAIRING_CONFIG_DIR)
        or not os.path.isdir(DEVICE_PAIRING_CONFIG_DIR)
    ):
        raise RuntimeError(
            f"Refusing unsafe device-pairing config path: {DEVICE_PAIRING_CONFIG_DIR}"
        )
    os.makedirs(DEVICE_PAIRING_CONFIG_DIR, mode=0o750, exist_ok=True)
    source_available = os.path.lexists(DEVICE_PAIRING_PAYLOAD_FILE)
    previous_payload = None
    if source_available:
        _validate_htpasswd_file(DEVICE_PAIRING_PAYLOAD_FILE)
        with open(DEVICE_PAIRING_PAYLOAD_FILE, "rb") as source_file:
            payload = source_file.read()
        existing = None
        if os.path.lexists(DEVICE_PAIRING_AUTH_FILE):
            if os.path.islink(DEVICE_PAIRING_AUTH_FILE) or not os.path.isfile(
                DEVICE_PAIRING_AUTH_FILE
            ):
                raise RuntimeError(
                    "Refusing unsafe device-pairing auth destination: "
                    f"{DEVICE_PAIRING_AUTH_FILE}"
                )
            with open(DEVICE_PAIRING_AUTH_FILE, "rb") as destination_file:
                existing = destination_file.read()
            previous_payload = existing
        changed = existing != payload
        if changed:
            _replace_pairing_auth_file(payload)
    else:
        if not os.path.exists(DEVICE_PAIRING_AUTH_FILE):
            raise RuntimeError(
                "Device pairing needs --device-pairing-auth-file on first setup "
                "or credentials entered through --interactive"
            )
        _validate_htpasswd_file(DEVICE_PAIRING_AUTH_FILE)
        with open(DEVICE_PAIRING_AUTH_FILE, "rb") as destination_file:
            previous_payload = destination_file.read()
        changed = False

    web_account = pwd.getpwnam("www-data")
    os.chown(DEVICE_PAIRING_CONFIG_DIR, 0, web_account.pw_gid)
    os.chmod(DEVICE_PAIRING_CONFIG_DIR, 0o750)
    os.chown(DEVICE_PAIRING_AUTH_FILE, 0, web_account.pw_gid)
    os.chmod(DEVICE_PAIRING_AUTH_FILE, 0o640)
    return changed, previous_payload


def _restore_pairing_auth_file(previous_payload: bytes | None) -> None:
    if previous_payload is None:
        if os.path.exists(DEVICE_PAIRING_AUTH_FILE):
            os.remove(DEVICE_PAIRING_AUTH_FILE)
        return
    _replace_pairing_auth_file(previous_payload)
    web_account = pwd.getpwnam("www-data")
    os.chown(DEVICE_PAIRING_AUTH_FILE, 0, web_account.pw_gid)
    os.chmod(DEVICE_PAIRING_AUTH_FILE, 0o640)


def _nginx_listen_address(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _configure_device_pairing(
    config: SetupConfig,
    home: str,
    t3_cli_wrapper: str,
    host: str,
    t3_port: int,
) -> None:
    from web.web_steps import install_nginx

    install_nginx(config)
    auth_changed, previous_auth = _install_pairing_auth_file()
    web_account = pwd.getpwnam("www-data")
    t3_state_dir = os.path.join(home, ".t3")
    os.makedirs(t3_state_dir, mode=0o700, exist_ok=True)
    account = pwd.getpwnam(config.username)
    os.chown(t3_state_dir, account.pw_uid, account.pw_gid)
    server_url, _default_base_url = _t3_pairing_urls(config.host, host, t3_port)

    providers = {
        "version": 1,
        "providers": {
            "t3code": {
                "label": "T3 Code",
                "command": [
                    "/usr/bin/python3",
                    T3_ADMIN_PAIR_SCRIPT,
                    "--t3-binary",
                    t3_cli_wrapper,
                    "--base-dir",
                    t3_state_dir,
                    "--server-url",
                    server_url,
                    "--label",
                    "infra-tools device enrollment",
                    "--json",
                ],
                "base_url_flag": "--base-url",
                "url_field": "pairUrl",
                "expires_field": "expiresAt",
                "public_port": t3_port,
                "connect": {
                    "link_command": [
                        t3_cli_wrapper,
                        "connect",
                        "link",
                        "--headless",
                        "--base-dir",
                        t3_state_dir,
                    ],
                    "status_command": [
                        t3_cli_wrapper,
                        "connect",
                        "status",
                        "--json",
                        "--base-dir",
                        t3_state_dir,
                    ],
                    "unlink_command": [
                        t3_cli_wrapper,
                        "connect",
                        "unlink",
                        "--base-dir",
                        t3_state_dir,
                    ],
                    "restart_request": os.path.join(
                        t3_state_dir,
                        "infra-tools-connect-restart",
                    ),
                },
            }
        },
    }
    providers_content = json.dumps(providers, indent=2, sort_keys=True) + "\n"
    providers_changed = _write_text_if_changed(
        DEVICE_PAIRING_PROVIDERS_FILE, providers_content, 0o640
    )
    os.chown(DEVICE_PAIRING_PROVIDERS_FILE, 0, web_account.pw_gid)

    service_content = f"""[Unit]
Description=infra-tools protected device-pairing broker
After=network-online.target {T3_SERVICE_NAME}.service nginx.service
Wants=network-online.target
Requires={T3_SERVICE_NAME}.service

[Service]
Type=simple
User={config.username}
Group=www-data
RuntimeDirectory=infra-tools-device-pairing
RuntimeDirectoryMode=0750
UMask=0007
Environment=HOME={home}
Environment=T3CODE_PORT={t3_port}
ExecStart=/usr/bin/python3 {DEVICE_PAIRING_SCRIPT} --config {DEVICE_PAIRING_PROVIDERS_FILE} --socket {DEVICE_PAIRING_SOCKET}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={t3_state_dir}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    service_changed = _write_text_if_changed(
        DEVICE_PAIRING_SERVICE_FILE, service_content, 0o644
    )
    if service_changed:
        run("systemctl daemon-reload")
    enabled = run(
        f"systemctl is-enabled {DEVICE_PAIRING_SERVICE_NAME}.service",
        check=False,
    )
    if enabled.returncode != 0:
        run(f"systemctl enable {DEVICE_PAIRING_SERVICE_NAME}.service")
    if service_changed or providers_changed:
        run(f"systemctl restart {DEVICE_PAIRING_SERVICE_NAME}.service")
    else:
        active = run(
            f"systemctl is-active {DEVICE_PAIRING_SERVICE_NAME}.service",
            check=False,
        )
        if active.returncode != 0:
            run(f"systemctl start {DEVICE_PAIRING_SERVICE_NAME}.service")

    nginx_content = f"""# Managed by infra_tools device pairing
limit_req_zone $binary_remote_addr zone=infra_tools_device_pairing_auth:10m rate=5r/m;

map $status $infra_tools_device_pairing_auth_failure {{
    default 0;
    401 1;
}}

log_format infra_tools_device_pairing_auth '$remote_addr [$time_local] infra-tools-auth-failure';

server {{
    listen {_nginx_listen_address(host, config.device_pairing_port)};
    server_name _;
    access_log {DEVICE_PAIRING_AUTH_FAILURE_LOG} infra_tools_device_pairing_auth
        if=$infra_tools_device_pairing_auth_failure;

    auth_basic "Device pairing";
    auth_basic_user_file {DEVICE_PAIRING_AUTH_FILE};
    client_max_body_size 4k;

    location / {{
        limit_req zone=infra_tools_device_pairing_auth burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://unix:{DEVICE_PAIRING_SOCKET}:/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 35s;
        proxy_send_timeout 35s;
    }}
}}
"""
    previous_nginx_content = None
    if os.path.lexists(DEVICE_PAIRING_NGINX_SITE):
        if os.path.islink(DEVICE_PAIRING_NGINX_SITE) or not os.path.isfile(
            DEVICE_PAIRING_NGINX_SITE
        ):
            raise RuntimeError(
                f"Refusing unmanaged Nginx pairing site: {DEVICE_PAIRING_NGINX_SITE}"
            )
        with open(DEVICE_PAIRING_NGINX_SITE, encoding="utf-8") as file_obj:
            previous_nginx_content = file_obj.read()
    nginx_changed = previous_nginx_content != nginx_content
    if nginx_changed:
        write_text_atomic(DEVICE_PAIRING_NGINX_SITE, nginx_content, mode=0o644)
    link_created = False
    if not os.path.islink(DEVICE_PAIRING_NGINX_LINK):
        if os.path.lexists(DEVICE_PAIRING_NGINX_LINK):
            raise RuntimeError(
                f"Refusing unmanaged Nginx pairing site: {DEVICE_PAIRING_NGINX_LINK}"
            )
        os.symlink(DEVICE_PAIRING_NGINX_SITE, DEVICE_PAIRING_NGINX_LINK)
        nginx_changed = True
        link_created = True
    validation = run("nginx -t", check=False, capture_output=True)
    if validation.returncode != 0:
        if previous_nginx_content is None:
            if os.path.exists(DEVICE_PAIRING_NGINX_SITE):
                os.remove(DEVICE_PAIRING_NGINX_SITE)
        else:
            write_text_atomic(
                DEVICE_PAIRING_NGINX_SITE,
                previous_nginx_content,
                mode=0o644,
            )
        if link_created and os.path.islink(DEVICE_PAIRING_NGINX_LINK):
            os.unlink(DEVICE_PAIRING_NGINX_LINK)
        if auth_changed:
            _restore_pairing_auth_file(previous_auth)
        raise RuntimeError("Nginx rejected the device-pairing configuration")
    if nginx_changed or auth_changed:
        run("systemctl reload nginx")
    configure_nginx_auth_failure_ban(
        "device-pairing",
        DEVICE_PAIRING_AUTH_FAILURE_LOG,
    )


def _remove_device_pairing() -> None:
    if os.path.islink(DEVICE_PAIRING_CONFIG_DIR):
        raise RuntimeError(
            f"Refusing unsafe device-pairing config path: {DEVICE_PAIRING_CONFIG_DIR}"
        )
    changed = False
    if os.path.exists(DEVICE_PAIRING_SERVICE_FILE):
        run(f"systemctl disable --now {DEVICE_PAIRING_SERVICE_NAME}.service", check=False)
        os.remove(DEVICE_PAIRING_SERVICE_FILE)
        run("systemctl daemon-reload")
    for path in (
        DEVICE_PAIRING_NGINX_LINK,
        DEVICE_PAIRING_NGINX_SITE,
        DEVICE_PAIRING_PROVIDERS_FILE,
        DEVICE_PAIRING_AUTH_FILE,
    ):
        if os.path.lexists(path):
            os.remove(path)
            changed = True
    if os.path.isdir(DEVICE_PAIRING_CONFIG_DIR):
        try:
            os.rmdir(DEVICE_PAIRING_CONFIG_DIR)
        except OSError:
            pass
    if changed and shutil.which("nginx"):
        validation = run("nginx -t", check=False, capture_output=True)
        if validation.returncode != 0:
            raise RuntimeError("Nginx configuration is invalid after removing device pairing")
        run("systemctl reload nginx", check=False)
    remove_nginx_auth_failure_ban("device-pairing")


def _configure_connect_restart_units(state_dir: str) -> None:
    """Install a root-owned path trigger for safe T3 service reconciliation."""

    request_path = os.path.join(state_dir, "infra-tools-connect-restart")
    path_content = f"""[Unit]
Description=Watch for T3 Connect service reconciliation requests

[Path]
PathExists={request_path}
Unit={T3_CONNECT_RESTART_SERVICE_UNIT}

[Install]
WantedBy=multi-user.target
"""
    service_content = f"""[Unit]
Description=Reconcile the managed T3 Connect service
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/rm -f {request_path}
ExecStart=/usr/bin/systemctl restart {T3_SERVICE_NAME}.service
"""
    path_changed = _write_text_if_changed(
        T3_CONNECT_RESTART_PATH_FILE,
        path_content,
        0o644,
    )
    service_changed = _write_text_if_changed(
        T3_CONNECT_RESTART_SERVICE_FILE,
        service_content,
        0o644,
    )
    if path_changed or service_changed:
        run("systemctl daemon-reload")
    enabled = run(
        f"systemctl is-enabled {T3_CONNECT_RESTART_PATH_UNIT}",
        check=False,
    )
    if enabled.returncode != 0:
        run(f"systemctl enable {T3_CONNECT_RESTART_PATH_UNIT}")
    active = run(
        f"systemctl is-active {T3_CONNECT_RESTART_PATH_UNIT}",
        check=False,
    )
    if active.returncode != 0:
        run(f"systemctl start {T3_CONNECT_RESTART_PATH_UNIT}")


def _remove_connect_restart_units() -> None:
    changed = False
    for unit_name, unit_path in (
        (T3_CONNECT_RESTART_PATH_UNIT, T3_CONNECT_RESTART_PATH_FILE),
        (T3_CONNECT_RESTART_SERVICE_UNIT, T3_CONNECT_RESTART_SERVICE_FILE),
    ):
        if os.path.lexists(unit_path):
            if os.path.islink(unit_path):
                raise RuntimeError(f"Refusing symlinked managed unit: {unit_path}")
            run(f"systemctl disable --now {unit_name}", check=False)
            os.remove(unit_path)
            changed = True
    if changed:
        run("systemctl daemon-reload")


def _configure_t3_https(
    config: SetupConfig,
    port: int,
    pairing_port: int | None,
) -> list[tuple[str, int]]:
    """Publish T3 web and pairing pages through the shared internal HTTPS gateway."""

    if os.geteuid() != 0:
        # Target setup is root-owned; keeping this a no-op makes dry unit tests
        # and unprivileged development imports side-effect free.
        return []

    from common.godot_web_steps import configure_internal_web_host, identities_for_config

    configure_internal_web_host(
        identities_for_config(config.host, config.system_hostname),
        [config.username],
        config.effective_web_interface_sources(),
        configure_static_site=True,
    )
    utility = "/usr/local/bin/infra-web"
    urls: list[tuple[str, int]] = []
    routes = [("t3code", port)]
    if pairing_port is not None:
        routes.append(("t3code-pairing", pairing_port))
    for name, target_port in routes:
        result = run(
            "SUDO_USER="
            + shlex.quote(config.username)
            + " "
            + shlex.quote(utility)
            + " forward add "
            + shlex.quote(name)
            + " --listen auto --to 127.0.0.1:"
            + str(target_port)
            + " --json",
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "HTTPS forward failed").strip()
            raise RuntimeError(f"Could not configure HTTPS T3 endpoint: {detail}")
        try:
            payload = json.loads(result.stdout)
            url = payload.get("url")
            listen = payload.get("listen")
        except (TypeError, ValueError):
            url = None
            listen = None
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(listen, int)
            or not 1024 <= listen <= 65535
        ):
            raise RuntimeError("HTTPS gateway returned an invalid T3 endpoint")
        urls.append((url, listen))
    return urls


def _set_pairing_https_port(https_port: int) -> None:
    if os.path.islink(DEVICE_PAIRING_PROVIDERS_FILE):
        raise RuntimeError(
            f"Refusing symlinked device-pairing provider configuration: "
            f"{DEVICE_PAIRING_PROVIDERS_FILE}"
        )
    with open(DEVICE_PAIRING_PROVIDERS_FILE, encoding="utf-8") as file_obj:
        providers = json.load(file_obj)
    if not isinstance(providers, dict) or not isinstance(providers.get("providers"), dict):
        raise RuntimeError("Invalid device-pairing provider configuration")
    t3_provider = providers["providers"].get("t3code")
    if not isinstance(t3_provider, dict):
        raise RuntimeError("T3 Code pairing provider is missing")
    if t3_provider.get("https_public_port") == https_port:
        return
    t3_provider["https_public_port"] = https_port
    _write_text_if_changed(
        DEVICE_PAIRING_PROVIDERS_FILE,
        json.dumps(providers, indent=2, sort_keys=True) + "\n",
        0o640,
    )
    web_account = pwd.getpwnam("www-data")
    os.chown(DEVICE_PAIRING_PROVIDERS_FILE, 0, web_account.pw_gid)
    os.chmod(DEVICE_PAIRING_PROVIDERS_FILE, 0o640)
    run(f"systemctl restart {DEVICE_PAIRING_SERVICE_NAME}.service")


def _remove_t3_https(config: SetupConfig) -> None:
    utility = "/usr/local/bin/infra-web"
    for name in ("t3code-pairing", "t3code"):
        run(
            "SUDO_USER="
            + shlex.quote(config.username)
            + " "
            + shlex.quote(utility)
            + " forward remove "
            + shlex.quote(name)
            + " --json",
            check=False,
            capture_output=True,
        )


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
    t3_binary, runtime_changed = _install_t3_runtime(
        home,
        config.username,
        account.pw_uid,
        account.pw_gid,
        refresh=config.refresh_packages,
    )
    wrapper = os.path.join(home, ".local", "bin", "infra-tools-t3code-web")
    pair_wrapper = os.path.join(home, ".local", "bin", "t3code-pair")
    t3_cli_wrapper = os.path.join(
        home, ".local", "bin", "infra-tools-t3code-pairing-provider"
    )
    if os.path.islink(T3_ADMIN_PAIR_SCRIPT) or not os.path.isfile(T3_ADMIN_PAIR_SCRIPT):
        raise RuntimeError(f"T3 administrative pairing helper is missing: {T3_ADMIN_PAIR_SCRIPT}")
    os.chmod(T3_ADMIN_PAIR_SCRIPT, 0o755)
    t3_cli_wrapper_changed = _write_passthrough_wrapper(
        t3_cli_wrapper,
        home,
        t3_binary,
    )
    legacy_shim_removed = _remove_legacy_t3_shim(home)
    wrapper_changed = _write_wrapper(
        wrapper,
        home,
        workspace,
        t3_binary,
        host,
        port,
        f"serve --host {shlex.quote(host)} --port {port} --no-browser",
    )
    server_url, base_url = _t3_pairing_urls(config.host, host, port)
    pair_wrapper_changed = _write_admin_pair_wrapper(
        pair_wrapper,
        home,
        workspace,
        t3_cli_wrapper,
        server_url,
        base_url,
    )
    os.chown(wrapper, account.pw_uid, account.pw_gid)
    os.chown(pair_wrapper, account.pw_uid, account.pw_gid)
    os.chown(t3_cli_wrapper, account.pw_uid, account.pw_gid)
    os.chown(workspace, account.pw_uid, account.pw_gid)
    skill_changed = _ensure_t3_agent_skill(
        config.username,
        config.selected_agent_tools(),
    )

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
    if os.path.islink(T3_SERVICE_FILE):
        raise RuntimeError(f"Refusing symlinked managed service file: {T3_SERVICE_FILE}")
    service_changed = True
    try:
        with open(T3_SERVICE_FILE, encoding="utf-8") as file_obj:
            service_changed = file_obj.read() != service_content
    except OSError:
        pass
    if service_changed:
        _write_text_if_changed(T3_SERVICE_FILE, service_content, 0o644)

    if service_changed:
        run("systemctl daemon-reload")
    enabled = run(
        f"systemctl is-enabled {T3_SERVICE_NAME}.service",
        check=False,
    )
    if enabled.returncode != 0:
        run(f"systemctl enable {T3_SERVICE_NAME}.service")

    if (
        service_changed
        or wrapper_changed
        or pair_wrapper_changed
        or t3_cli_wrapper_changed
        or runtime_changed
        or skill_changed
        or legacy_shim_removed
    ):
        run(f"systemctl restart {T3_SERVICE_NAME}.service")
    else:
        active = run(
            f"systemctl is-active {T3_SERVICE_NAME}.service",
            check=False,
        )
        if active.returncode != 0:
            run(f"systemctl start {T3_SERVICE_NAME}.service")
    if config.device_pairing_providers:
        _configure_connect_restart_units(os.path.join(home, ".t3"))
        _configure_device_pairing(config, home, t3_cli_wrapper, host, port)
        https_urls = _configure_t3_https(
            config,
            port,
            config.device_pairing_port,
        )
        if https_urls:
            _set_pairing_https_port(https_urls[0][1])
    else:
        _remove_connect_restart_units()
        _remove_device_pairing()
        _remove_t3_https(config)
        https_urls = _configure_t3_https(config, port, None)
    print(f"  T3 Code web service listening on {host}:{port}")
    print(f"  T3 Code endpoint: {base_url}")
    for https_url, _listen_port in https_urls:
        print(f"  T3 Code HTTPS endpoint: {https_url}")
    print("  Readiness check: infra-tools agent doctor --capability t3code")
    if config.device_pairing_providers:
        print(
            "  Protected device enrollment listening on "
            f"{host}:{config.device_pairing_port}"
        )
    else:
        print(
            "  Pairing is required: run 'infra-tools agent web pair HOST USER' "
            "from the control system"
        )
    print(
        "  Use the full one-time pairing URL; the bare web address intentionally "
        "shows a pairing-key form"
    )
    if config.install_gh:
        print(
            "  GitHub authentication is server-side; use 'gh auth status' as the "
            "target user and keep repository URLs on HTTPS"
        )


__all__ = ["install_t3code_web"]
