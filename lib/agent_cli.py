"""Local agentic coding tool diagnostics and lifecycle management."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from lib.atomic_io import write_json_atomic
from lib.agent_auth import AGENT_AUTH_TOOLS
from lib.ssh_utils import build_ssh_command, shell_join, ssh_batch_mode
from lib.types import JSONDict, StrList
from lib.validation import validate_filesystem_path, validate_package_name
from lib.validators import validate_host, validate_username


AGENT_DOCTOR_TOOLS = ("gh", "codex", "claude", "opencode")
AGENT_DOCTOR_CAPABILITIES = ("browser",)
DEFAULT_DOCTOR_TOOLS = ("gh", "codex", "claude", "opencode")
AGENT_UPDATE_TOOLS = ("codex", "claude", "opencode")
DEFAULT_UPDATE_TOOLS = AGENT_UPDATE_TOOLS

_AGENT_STATE_RELATIVE = os.path.join(
    ".local",
    "state",
    "infra_tools",
    "agent-tools.json",
)
_CODEX_INSTALLER_URL = "https://chatgpt.com/codex/install.sh"
_MAX_INSTALLER_BYTES = 4 * 1024 * 1024
_UPDATE_TIMEOUT_SECONDS = 600
_BROWSER_MCP_WRAPPER = "/usr/local/bin/infra-tools-playwright-mcp"
_BROWSER_DOCTOR_WRAPPER = "/usr/local/bin/infra-tools-playwright-doctor"
_BROWSER_MCP_SERVER_NAME = "infra-tools-playwright"
_REMOTE_INFRA_TOOLS_PATH = "/opt/infra_tools/infra_tools.py"

_CREDENTIAL_PATHS = {
    "gh": ".config/gh/hosts.yml",
    "codex": ".codex/auth.json",
    "claude": ".claude/.credentials.json",
    "opencode": ".local/share/opencode/auth.json",
}

_UPDATE_ENVIRONMENT_REDIRECTS = {
    "bash_env",
    "cdpath",
    "codex_home",
    "env",
    "git_config_global",
    "nvm_dir",
    "oldpwd",
    "pwd",
    "tmpdir",
    "xdg_cache_home",
    "xdg_config_home",
    "xdg_data_home",
    "xdg_state_home",
}
_UPDATE_SYSTEM_PATH = os.pathsep.join(
    ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
)


def add_agent_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add local agent-tool management commands."""
    parser = subparsers.add_parser(
        "agent",
        help="Inspect local agentic coding tools",
    )
    commands = parser.add_subparsers(dest="agent_command", help="Agent commands")
    doctor = commands.add_parser(
        "doctor",
        help="Check installed agent tools and local credential files",
    )
    doctor.add_argument(
        "agent_doctor_host",
        nargs="?",
        metavar="HOST",
        help="Remote agent VM to inspect; omit HOST and USER for a local check",
    )
    doctor.add_argument(
        "agent_doctor_username",
        nargs="?",
        metavar="USER",
        help="Remote agent VM user",
    )
    doctor.add_argument(
        "--tool",
        dest="agent_doctor_tools",
        action="append",
        choices=AGENT_DOCTOR_TOOLS,
        help="Tool to require; repeat as needed",
    )
    doctor.add_argument(
        "--capability",
        dest="agent_doctor_capabilities",
        action="append",
        choices=AGENT_DOCTOR_CAPABILITIES,
        help="Provisioned agent capability to verify; repeat as needed",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    doctor.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    update = commands.add_parser(
        "update",
        help="Deliberately update user-installed terminal agents",
    )
    update.add_argument(
        "agent_update_host",
        nargs="?",
        metavar="HOST",
        help="Remote agent VM to update; omit HOST and USER for a local update",
    )
    update.add_argument(
        "agent_update_username",
        nargs="?",
        metavar="USER",
        help="Remote agent VM user",
    )
    update.add_argument(
        "--tool",
        dest="agent_update_tools",
        action="append",
        choices=AGENT_UPDATE_TOOLS,
        help="Tool to update; repeat as needed (default: all terminal agents)",
    )
    update.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the selected update mechanisms without changing tools",
    )
    update.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    update.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    auth = commands.add_parser(
        "auth",
        help="Rotate or inspect credentials on an agent VM",
    )
    auth_commands = auth.add_subparsers(
        dest="agent_auth_command",
        help="Credential operations",
    )
    auth_set = auth_commands.add_parser(
        "set",
        help="Atomically replace one target credential",
    )
    auth_set.add_argument("agent_auth_host", metavar="HOST")
    auth_set.add_argument("agent_auth_username", metavar="USER")
    auth_set.add_argument(
        "--tool",
        dest="agent_auth_tool",
        required=True,
        choices=AGENT_AUTH_TOOLS,
        help="Credential to replace",
    )
    auth_source = auth_set.add_mutually_exclusive_group()
    auth_source.add_argument(
        "--file",
        dest="agent_auth_file",
        metavar="PATH",
        help="Controller-local credential file",
    )
    auth_source.add_argument(
        "--active",
        dest="agent_auth_active",
        action="store_true",
        help="Use the active controller user's credential file",
    )
    auth_source.add_argument(
        "--interactive",
        dest="agent_auth_interactive",
        action="store_true",
        help="Choose the source interactively",
    )
    auth_set.add_argument(
        "--git-host",
        default="github.com",
        metavar="HOST",
        help="GitHub host for gh credentials (default: github.com)",
    )
    auth_set.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")

    auth_status = auth_commands.add_parser(
        "status",
        help="Show non-secret credential and authentication status",
    )
    auth_status.add_argument("agent_auth_host", metavar="HOST")
    auth_status.add_argument("agent_auth_username", metavar="USER")
    auth_status.add_argument(
        "--tool",
        dest="agent_auth_tools",
        action="append",
        choices=AGENT_AUTH_TOOLS,
        help="Tool to inspect; repeat as needed",
    )
    auth_status.add_argument(
        "--git-host",
        default="github.com",
        metavar="HOST",
        help="GitHub host to check with gh (default: github.com)",
    )
    auth_status.add_argument("--json", action="store_true", help="Output JSON")
    auth_status.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    web = commands.add_parser(
        "web",
        help="Pair with a remote agent web interface",
    )
    web_commands = web.add_subparsers(
        dest="agent_web_command",
        help="Web interface operations",
    )
    web_pair = web_commands.add_parser(
        "pair",
        help="Print a fresh T3 Code pairing URL from a remote VM",
    )
    web_pair.add_argument("agent_web_host", metavar="HOST")
    web_pair.add_argument("agent_web_username", metavar="USER")
    web_pair.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")


def _tool_path(tool: str, home: str) -> Optional[str]:
    search_path = os.pathsep.join(
        (
            os.path.join(home, ".local", "bin"),
            os.path.join(home, ".opencode", "bin"),
            _UPDATE_SYSTEM_PATH,
        )
    )
    return shutil.which(tool, path=search_path)


def _tool_version(tool: str, path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _tool_smoke_test(path: str) -> bool:
    try:
        result = subprocess.run(
            [path, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool((result.stdout or result.stderr).strip())


def _validate_update_tools(tools: StrList) -> None:
    for tool in dict.fromkeys(tools):
        validate_package_name(tool, name="agent tool")
        if tool not in AGENT_UPDATE_TOOLS:
            raise ValueError(f"Unsupported agent update tool: {tool}")


def _state_path(home: str) -> str:
    path = os.path.join(home, _AGENT_STATE_RELATIVE)
    validate_filesystem_path(path, must_exist=False)
    return path


def _load_update_state(path: str) -> JSONDict:
    if not os.path.exists(path):
        return {"schema_version": 1, "tools": {}}
    try:
        with open(path, encoding="utf-8") as file_obj:
            value = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read agent update state: {path}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("tools"), dict)
    ):
        raise RuntimeError(f"Unsupported agent update state: {path}")
    return value


def _save_update_state(path: str, state: JSONDict) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    os.chmod(parent, 0o700)
    write_json_atomic(path, state, mode=0o600, sort_keys=True)


def _within_home(path: str, home: str) -> bool:
    try:
        resolved_home = os.path.realpath(home)
        return os.path.commonpath((os.path.realpath(path), resolved_home)) == resolved_home
    except ValueError:
        return False


def _validate_update_identity(home: str) -> pwd.struct_passwd:
    """Require updates to run as the owner of the user-scoped installation."""

    try:
        owner = pwd.getpwuid(os.stat(home).st_uid)
    except (OSError, KeyError) as exc:
        raise RuntimeError(f"Could not determine the owner of agent home: {home}") from exc

    if os.geteuid() != owner.pw_uid:
        try:
            current_user = pwd.getpwuid(os.geteuid()).pw_name
        except KeyError:
            current_user = str(os.geteuid())
        raise RuntimeError(
            f"Agent updates for {home} must run as {owner.pw_name}; "
            f"current user is {current_user}. Use 'sudo -u {owner.pw_name} -H'."
        )
    return owner


def _agent_update_environment(home: str, owner: pwd.struct_passwd) -> dict[str, str]:
    """Build an environment rooted in the account being updated.

    ``sudo -u`` normally preserves the caller's working directory and some
    environment variables. Vendor installers may use those values while
    changing directories, causing an unprivileged account to touch the
    caller's home. Keep useful inherited values such as proxy and agent
    sockets, but remove path/home redirects and replace them with the target
    account's locations.
    """

    environment = os.environ.copy()
    for key in list(environment):
        normalized = key.lower()
        if normalized.startswith("sudo_"):
            environment.pop(key, None)
        elif normalized in _UPDATE_ENVIRONMENT_REDIRECTS:
            environment.pop(key, None)
        elif normalized in {
            "npm_config_userconfig",
            "npm_config_prefix",
            "npm_config_cache",
        }:
            environment.pop(key, None)

    environment.update(
        {
            "HOME": home,
            "LOGNAME": owner.pw_name,
            "PATH": os.pathsep.join(
                (
                    os.path.join(home, ".local", "bin"),
                    os.path.join(home, ".opencode", "bin"),
                    _UPDATE_SYSTEM_PATH,
                )
            ),
            "PWD": home,
            "TMPDIR": "/tmp",
            "USER": owner.pw_name,
            "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
            "CODEX_HOME": os.path.join(home, ".codex"),
            "NVM_DIR": os.path.join(home, ".nvm"),
        }
    )
    return environment


def _backup_executable(tool: str, path: str, home: str) -> str:
    backup_dir = os.path.join(
        home,
        ".local",
        "state",
        "infra_tools",
        "agent-backups",
    )
    validate_filesystem_path(backup_dir, must_exist=False)
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    backup_path = os.path.join(backup_dir, f"{tool}.previous")
    descriptor, temporary_path = tempfile.mkstemp(
        dir=backup_dir,
        prefix=f".{tool}-",
    )
    os.close(descriptor)
    try:
        shutil.copy2(os.path.realpath(path), temporary_path)
        with open(temporary_path, "rb") as file_obj:
            os.fsync(file_obj.fileno())
        os.replace(temporary_path, backup_path)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
    return backup_path


def _restore_executable(path: str, backup_path: str) -> bool:
    parent = os.path.dirname(path)
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            dir=parent,
            prefix=".infra-tools-rollback-",
        )
        os.close(descriptor)
        os.unlink(temporary_path)
        try:
            os.symlink(backup_path, temporary_path)
            os.replace(temporary_path, path)
        finally:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
    except OSError:
        return False
    return True


def _download_codex_installer(directory: str) -> tuple[str, str]:
    request = urllib.request.Request(
        _CODEX_INSTALLER_URL,
        headers={"User-Agent": "infra-tools-agent-updater/1"},
    )
    descriptor, installer_path = tempfile.mkstemp(
        dir=directory,
        prefix=".codex-installer-",
        suffix=".sh",
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as file_obj:
            with urllib.request.urlopen(request, timeout=60) as response:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > _MAX_INSTALLER_BYTES:
                        raise RuntimeError("Codex installer exceeds the size limit")
                    digest.update(chunk)
                    file_obj.write(chunk)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        if size == 0:
            raise RuntimeError("Codex installer download was empty")
        os.chmod(installer_path, 0o600)
        return installer_path, digest.hexdigest()
    except (OSError, RuntimeError):
        try:
            os.unlink(installer_path)
        except FileNotFoundError:
            pass
        raise


def _invoke_agent_update(tool: str, path: str, home: str) -> JSONDict:
    owner = _validate_update_identity(home)
    environment = _agent_update_environment(home, owner)
    installer_path: Optional[str] = None
    installer_sha256: Optional[str] = None
    if tool == "codex":
        installer_path, installer_sha256 = _download_codex_installer(
            os.path.dirname(_state_path(home)),
        )
        command = ["/bin/sh", installer_path]
        method = _CODEX_INSTALLER_URL
    elif tool == "claude":
        command = [path, "update"]
        method = "claude update"
    else:
        command = [path, "upgrade"]
        method = "opencode upgrade"

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_UPDATE_TIMEOUT_SECONDS,
            env=environment,
            cwd=home,
        )
        return {
            "returncode": result.returncode,
            "method": method,
            "installer_sha256": installer_sha256,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": None,
            "method": method,
            "installer_sha256": installer_sha256,
            "failure": "timeout",
        }
    except OSError:
        return {
            "returncode": None,
            "method": method,
            "installer_sha256": installer_sha256,
            "failure": "execution_error",
        }
    finally:
        if installer_path:
            try:
                os.unlink(installer_path)
            except FileNotFoundError:
                pass


def _update_method(tool: str) -> str:
    if tool == "codex":
        return _CODEX_INSTALLER_URL
    return f"{tool} {'update' if tool == 'claude' else 'upgrade'}"


def update_agent_tools(
    tools: StrList,
    *,
    home: Optional[str] = None,
    dry_run: bool = False,
) -> list[JSONDict]:
    """Update user-installed agents and persist non-secret verification records."""
    _validate_update_tools(tools)
    user_home = os.path.abspath(home or os.path.expanduser("~"))
    validate_filesystem_path(user_home, must_exist=True)
    _validate_update_identity(user_home)
    state_path = _state_path(user_home)
    state = _load_update_state(state_path) if not dry_run else None
    results: list[JSONDict] = []

    for tool in dict.fromkeys(tools):
        path = _tool_path(tool, user_home)
        before_version = _tool_version(tool, path) if path else None
        record: JSONDict = {
            "tool": tool,
            "path": path,
            "method": _update_method(tool),
            "before_version": before_version,
            "after_version": before_version,
            "status": "planned" if dry_run else "failed",
            "rollback": False,
        }
        if not path:
            record["failure"] = "not_installed"
            record["status"] = "failed"
            results.append(record)
            continue
        if not _within_home(path, user_home):
            record["failure"] = "not_user_managed"
            record["status"] = "failed"
            results.append(record)
            continue
        if not before_version or not _tool_smoke_test(path):
            record["failure"] = "pre_update_verification"
            record["status"] = "failed"
            results.append(record)
            continue
        if dry_run:
            results.append(record)
            continue

        assert state is not None
        attempted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record["attempted_at"] = attempted_at
        try:
            backup_path = _backup_executable(tool, path, user_home)
        except OSError:
            record["failure"] = "backup_error"
            state["tools"][tool] = record
            _save_update_state(state_path, state)
            results.append(record)
            continue
        record["backup_path"] = backup_path
        state["tools"][tool] = {**record, "status": "in_progress"}
        _save_update_state(state_path, state)

        try:
            invocation = _invoke_agent_update(tool, path, user_home)
        except (OSError, RuntimeError):
            invocation = {
                "returncode": None,
                "method": _update_method(tool),
                "installer_sha256": None,
                "failure": "download_error",
            }
        record.update(invocation)
        current_path = _tool_path(tool, user_home)
        after_version = _tool_version(tool, current_path) if current_path else None
        smoke_ok = bool(current_path and _tool_smoke_test(current_path))
        record["path"] = current_path
        record["after_version"] = after_version

        if invocation.get("returncode") == 0 and after_version and smoke_ok:
            record["status"] = "updated" if after_version != before_version else "current"
        else:
            record["status"] = "failed"
            if "failure" not in record:
                record["failure"] = (
                    "updater_exit" if invocation.get("returncode") != 0 else "post_update_verification"
                )
            if after_version != before_version or not smoke_ok:
                restored = _restore_executable(path, backup_path)
                restored_version = _tool_version(tool, path) if restored else None
                restored_smoke = restored and _tool_smoke_test(path)
                record["rollback"] = bool(
                    restored
                    and restored_version == before_version
                    and restored_smoke
                )
                if restored:
                    record["path"] = path
                    record["after_version"] = restored_version
                if restored and not record["rollback"]:
                    record["rollback_failure"] = "verification"

        state["tools"][tool] = record
        _save_update_state(state_path, state)
        results.append(record)

    return results


def inspect_agent_tools(tools: StrList, home: Optional[str] = None) -> list[JSONDict]:
    """Return non-secret installation and credential status for selected tools."""
    user_home = home or os.path.expanduser("~")
    results: list[JSONDict] = []
    for tool in tools:
        path = _tool_path(tool, user_home)
        credential_relative = _CREDENTIAL_PATHS.get(tool)
        result: JSONDict = {
            "tool": tool,
            "installed": path is not None,
            "path": path,
            "version": _tool_version(tool, path) if path else None,
            "credential": (
                os.path.exists(os.path.join(user_home, credential_relative))
                if credential_relative
                else None
            ),
        }
        results.append(result)
    return results


def _codex_browser_registration(home: str) -> bool:
    config_path = os.path.join(home, ".codex", "config.toml")
    try:
        with open(config_path, encoding="utf-8") as file_obj:
            content = file_obj.read()
    except OSError:
        return False
    escaped_name = re.escape(_BROWSER_MCP_SERVER_NAME)
    section = re.search(
        rf'^\[mcp_servers\.(?:{escaped_name}|"{escaped_name}")\]\s*$',
        content,
        re.MULTILINE,
    )
    if section is None:
        return False

    following_section = re.search(r'^\[', content[section.end():], re.MULTILINE)
    section_content = content[section.end():]
    if following_section is not None:
        section_content = section_content[:following_section.start()]
    command = re.search(
        r'^\s*command\s*=\s*(?:"([^"]*)"|\'([^\']*)\')\s*(?:#.*)?$',
        section_content,
        re.MULTILINE,
    )
    return bool(command and (command.group(1) or command.group(2)) == _BROWSER_MCP_WRAPPER)


def _opencode_browser_registration(home: str) -> bool:
    from common.browser_automation_steps import _load_opencode_config, _opencode_config_path

    config_dir = os.path.join(home, ".config", "opencode")
    config_path = _opencode_config_path(config_dir)
    try:
        value = _load_opencode_config(config_path)
    except (OSError, ValueError):
        return False
    if not isinstance(value.get("mcp"), dict):
        return False
    registration = value["mcp"].get(_BROWSER_MCP_SERVER_NAME)
    return bool(
        isinstance(registration, dict)
        and registration.get("type") == "local"
        and registration.get("enabled") is True
        and registration.get("command") == [_BROWSER_MCP_WRAPPER]
        and registration.get("timeout") == 30000
    )


def inspect_browser_automation(home: Optional[str] = None) -> JSONDict:
    """Verify local launchers, selected-agent registration, and browser startup."""
    user_home = home or os.path.expanduser("~")
    launchers_installed = all(
        os.path.isfile(path) and os.access(path, os.X_OK)
        for path in (_BROWSER_MCP_WRAPPER, _BROWSER_DOCTOR_WRAPPER)
    )

    registrations: JSONDict = {}
    if _tool_path("codex", user_home):
        registrations["codex"] = _codex_browser_registration(user_home)
    if _tool_path("opencode", user_home):
        registrations["opencode"] = _opencode_browser_registration(user_home)

    smoke_test = False
    if launchers_installed:
        environment = os.environ.copy()
        environment["HOME"] = user_home
        try:
            result = subprocess.run(
                [_BROWSER_DOCTOR_WRAPPER],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                env=environment,
                cwd=user_home,
            )
            smoke_test = result.returncode == 0 and result.stdout.strip() == "browser-ready"
        except (OSError, subprocess.TimeoutExpired):
            smoke_test = False

    healthy = bool(
        launchers_installed
        and smoke_test
        and registrations
        and all(bool(value) for value in registrations.values())
    )
    return {
        "capability": "browser",
        "installed": launchers_installed,
        "path": _BROWSER_MCP_WRAPPER if launchers_installed else None,
        "registrations": registrations,
        "smoke_test": smoke_test,
        "healthy": healthy,
    }


def run_agent_web_pair(args: argparse.Namespace) -> int:
    """Ask a remote T3 Code service to mint a one-time pairing URL."""

    host = str(args.agent_web_host)
    username = str(args.agent_web_username)
    if not validate_host(host):
        print(f"Error: Invalid IP address or hostname: {host}")
        return 1
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1

    command = build_ssh_command(
        host,
        username,
        args.ssh_key,
        batch_mode=ssh_batch_mode(),
        remote_command="exec ~/.local/bin/t3code-pair",
        connect_timeout=30,
        server_alive_interval=30,
    )
    try:
        result = subprocess.run(command, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Error: could not obtain T3 Code pairing URL: {exc}")
        return 1
    if result.returncode != 0:
        print(f"Error: remote T3 Code pairing command failed (exit {result.returncode})")
        return 1
    return 0


def _remote_agent_target(
    args: argparse.Namespace,
    *,
    host_attribute: str,
    username_attribute: str,
) -> tuple[str, str, Optional[str]] | None:
    host_value = getattr(args, host_attribute, None)
    username_value = getattr(args, username_attribute, None)
    ssh_key_value = getattr(args, "ssh_key", None)
    if host_value is None and username_value is None:
        if ssh_key_value:
            raise ValueError("--key requires a remote HOST and USER")
        return None
    if host_value is None or username_value is None:
        raise ValueError("remote agent operations require both HOST and USER")

    host = str(host_value)
    username = str(username_value)
    if not validate_host(host):
        raise ValueError(f"Invalid IP address or hostname: {host}")
    if not validate_username(username):
        raise ValueError(f"Invalid username: {username}")

    ssh_key: Optional[str] = None
    if ssh_key_value:
        ssh_key = os.path.abspath(os.path.expanduser(str(ssh_key_value)))
        validate_filesystem_path(ssh_key, must_exist=True)
        if not os.path.isfile(ssh_key) or not os.access(ssh_key, os.R_OK):
            raise ValueError(f"SSH private key is not a readable file: {ssh_key}")
    return host, username, ssh_key


def _run_remote_agent_lifecycle(
    target: tuple[str, str, Optional[str]],
    subcommand: str,
    remote_arguments: StrList,
    *,
    timeout: int,
) -> int:
    """Run one target-user agent lifecycle command over managed SSH."""
    host, username, ssh_key = target
    remote_command = shell_join(
        [
            "python3",
            _REMOTE_INFRA_TOOLS_PATH,
            "agent",
            subcommand,
            *remote_arguments,
        ]
    )
    command = build_ssh_command(
        host,
        username,
        ssh_key,
        batch_mode=ssh_batch_mode(),
        remote_command=remote_command,
        connect_timeout=30,
        server_alive_interval=30,
    )
    try:
        result = subprocess.run(command, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Error: remote agent {subcommand} failed: {exc}")
        return 1
    return result.returncode


def run_agent_command(args: argparse.Namespace) -> int:
    """Run a local or remote agent-tool command."""
    if args.agent_command == "web":
        if args.agent_web_command == "pair":
            return run_agent_web_pair(args)
        print("Error: agent web command required (pair)")
        return 1

    if args.agent_command == "auth":
        from lib.agent_auth import run_agent_auth_set, run_agent_auth_status

        try:
            if args.agent_auth_command == "set":
                return run_agent_auth_set(args)
            if args.agent_auth_command == "status":
                return run_agent_auth_status(args)
        except (OSError, RuntimeError, ValueError, EOFError, KeyboardInterrupt) as exc:
            print(f"Error: {exc}")
            return 1
        print("Error: agent auth command required (set or status)")
        return 1

    if args.agent_command == "update":
        selected = list(args.agent_update_tools or DEFAULT_UPDATE_TOOLS)
        try:
            target = _remote_agent_target(
                args,
                host_attribute="agent_update_host",
                username_attribute="agent_update_username",
            )
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        if target is not None:
            remote_arguments: StrList = []
            for tool in args.agent_update_tools or []:
                remote_arguments.extend(("--tool", tool))
            if args.dry_run:
                remote_arguments.append("--dry-run")
            if args.json:
                remote_arguments.append("--json")
            return _run_remote_agent_lifecycle(
                target,
                "update",
                remote_arguments,
                timeout=(_UPDATE_TIMEOUT_SECONDS * len(selected)) + 60,
            )
        try:
            results = update_agent_tools(selected, dry_run=args.dry_run)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            heading = "Agent update plan" if args.dry_run else "Agent update result"
            print(heading)
            for result in results:
                tool = str(result["tool"])
                status = str(result["status"])
                if status == "planned":
                    print(
                        f"  • {tool}: {result['method']} ({result['before_version']})"
                        f" at {result.get('path') or 'unknown path'}"
                    )
                elif status in ("updated", "current"):
                    print(
                        f"  ✓ {tool}: {status} "
                        f"({result['before_version']} → {result['after_version']})"
                        f" at {result.get('path') or 'unknown path'}"
                    )
                else:
                    detail = str(result.get("failure", "unknown_error"))
                    if result.get("returncode") is not None:
                        detail += f" (exit {result['returncode']})"
                    rollback = "; rollback restored" if result.get("rollback") else ""
                    if result.get("rollback_failure"):
                        rollback = "; rollback verification failed"
                    print(
                        f"  ✗ {tool}: {detail}{rollback}"
                        f" at {result.get('path') or 'unknown path'}"
                    )
        return 0 if all(result["status"] in ("planned", "updated", "current") for result in results) else 1

    if args.agent_command != "doctor":
        print("Error: agent command required (doctor or update)")
        return 1

    requested_tools = getattr(args, "agent_doctor_tools", None)
    requested_capabilities = getattr(args, "agent_doctor_capabilities", None) or []
    try:
        target = _remote_agent_target(
            args,
            host_attribute="agent_doctor_host",
            username_attribute="agent_doctor_username",
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if target is not None:
        remote_arguments = []
        for tool in requested_tools or []:
            remote_arguments.extend(("--tool", tool))
        for capability in requested_capabilities:
            remote_arguments.extend(("--capability", capability))
        if args.json:
            remote_arguments.append("--json")
        return _run_remote_agent_lifecycle(
            target,
            "doctor",
            remote_arguments,
            timeout=180,
        )
    if requested_tools:
        selected = list(requested_tools)
    elif requested_capabilities:
        selected = []
    else:
        selected = list(DEFAULT_DOCTOR_TOOLS)
    results = inspect_agent_tools(selected)
    capability_results = [
        inspect_browser_automation()
        for capability in requested_capabilities
        if capability == "browser"
    ]
    if args.json:
        print(json.dumps([*results, *capability_results], indent=2))
    else:
        print("Agent tool check")
        for result in results:
            tool = str(result["tool"])
            if not result["installed"]:
                print(f"  ✗ {tool}: not installed")
                continue
            version = result.get("version")
            detail = f" ({version})" if version else ""
            print(f"  ✓ {tool}: {result['path']}{detail}")
            credential = result.get("credential")
            if credential is True:
                print("      credentials: present")
            elif credential is False:
                print("      credentials: not found; run the tool to sign in")

        for result in capability_results:
            if result["healthy"]:
                print(f"  ✓ browser: {result['path']} (smoke test passed)")
            elif not result["installed"]:
                print("  ✗ browser: Playwright launchers are not installed")
            elif not result["smoke_test"]:
                print("  ✗ browser: local smoke test failed")
            else:
                print("  ✗ browser: agent MCP registration is missing")

    tools_healthy = all(bool(result["installed"]) for result in results)
    capabilities_healthy = all(bool(result["healthy"]) for result in capability_results)
    return 0 if tools_healthy and capabilities_healthy else 1
