"""Installation and migration guards for the shared desktop runtime."""

from __future__ import annotations

import json
from pathlib import Path
import pwd
import shlex

from desktop.session_runtime import CONFIG_PATH, SESSION_COMMANDS
from lib.atomic_io import write_text_atomic
from lib.config import SetupConfig
from lib.machine_state import can_manage_system_services
from lib.remote_utils import is_dry_run, run
from lib.validation import validate_filesystem_path
from lib.validators import validate_username

STARTWM = "/etc/xrdp/infra-tools-startwm.sh"
DISPLAY_MANAGERS = ("gdm3", "gdm", "lightdm", "sddm", "lxdm", "xdm")
DISPLAY_MANAGER_ALIAS = Path("/etc/systemd/system/display-manager.service")


def assert_desktop_idle(config: SetupConfig) -> None:
    """Refuse disruptive setup while any user graphical session exists."""
    if config.desktop not in SESSION_COMMANDS:
        raise ValueError("Unsupported shared desktop environment")
    if not validate_username(config.username) or config.username == "root":
        raise ValueError("The desktop owner must be a valid non-root account")
    if not can_manage_system_services(config.machine_type):
        raise ValueError("Shared desktops require persistent systemd services")
    if config.harden_user:
        raise ValueError("Shared desktops require user services and cannot use --harden-user")
    if is_dry_run():
        print("  [DRY-RUN] Would require graphical sessions to be logged out before desktop changes")
        return
    sessions = run(["loginctl", "list-sessions", "--no-legend"], capture_output=True)
    for line in sessions.stdout.splitlines():
        if not line.strip():
            continue
        session_id = line.split()[0]
        details = run(["loginctl", "show-session", session_id, "-p", "Type", "-p", "Class"], capture_output=True)
        properties = dict(line.split("=", 1) for line in details.stdout.splitlines() if "=" in line)
        if properties.get("Type") in {"x11", "wayland"} and properties.get("Class") != "greeter":
            raise RuntimeError("Desktop setup deferred: log out existing graphical sessions and rerun; applications were not stopped")
    result = run(["pgrep", "-x", "xrdp-sesexec"], check=False, capture_output=True)
    if result.returncode == 0:
        raise RuntimeError("Desktop setup deferred: log out existing XRDP sessions and rerun")
    if result.returncode != 1:
        raise RuntimeError("Could not inspect XRDP sessions before desktop setup")


def prepare_shared_desktop(config: SetupConfig) -> None:
    """Retire console display managers so all managed GUI logins use sesman."""
    assert_desktop_idle(config)
    if is_dry_run():
        print("  [DRY-RUN] Would disable console graphical login; desktop access uses XRDP")
        return
    alias = DISPLAY_MANAGER_ALIAS
    masked = alias.is_symlink() and alias.resolve() == Path("/dev/null")
    if alias.exists() and not masked and alias.resolve().stem not in DISPLAY_MANAGERS:
        raise RuntimeError("Unrecognized console display manager; migrate its configuration before shared desktop setup")
    # Preserve the former alias for explicit administrator rollback.
    backup = alias.with_suffix(".service.infra-tools-backup")
    if alias.is_symlink() and not masked and not backup.is_symlink() and not backup.exists():
        backup.symlink_to(alias.readlink())
    if alias.is_symlink() and not masked:
        alias.unlink()
    run(["systemctl", "mask", "--now", "display-manager.service",
         *(f"{name}.service" for name in DISPLAY_MANAGERS)])
    print("  Console graphical login disabled; use the shared XRDP desktop")


def install_session_runtime(config: SetupConfig) -> None:
    """Install a root-owned startup path and the single authorized account."""
    if config.desktop not in SESSION_COMMANDS:
        raise ValueError("Unsupported shared desktop environment")
    if is_dry_run():
        print("  [DRY-RUN] Would install single-owner desktop runtime and local control tools")
        return
    assert_desktop_idle(config)
    account = pwd.getpwnam(config.username)
    if account.pw_uid == 0:
        raise ValueError("The desktop cannot run as root")
    source = str(Path(__file__).resolve().parents[1])
    validate_filesystem_path(source, must_exist=True)
    content = json.dumps({"version": 1, "username": config.username, "desktop": config.desktop}, indent=2) + "\n"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.parent.is_symlink() or CONFIG_PATH.is_symlink():
        raise RuntimeError("Refusing symlinked desktop configuration")
    if CONFIG_PATH.exists():
        previous = CONFIG_PATH.read_text()
        old = json.loads(previous)
        if not isinstance(old, dict) or old.get("version") != 1:
            raise RuntimeError("Unrecognized desktop configuration; refusing to replace it")
        backup = CONFIG_PATH.with_suffix(".json.bak")
        if not backup.exists():
            write_text_atomic(str(backup), previous, mode=0o600)
    write_text_atomic(str(CONFIG_PATH), content, mode=0o644)
    run(["groupadd", "-f", "infra-desktop"])
    run(["gpasswd", "-M", config.username, "infra-desktop"])
    script = (
        "#!/bin/sh\n# Managed by infra_tools shared desktop setup\n"
        "umask 077\nexport XRDP_SESSION=1\n"
        'export PATH="$HOME/.local/bin:$PATH"\n'
        'export XDG_SESSION_TYPE=x11\n'
        "unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER\n"
        f"cd {shlex.quote(source)} || exit 1\n"
        "exec dbus-run-session -- /usr/bin/python3 -m desktop.session_runtime\n"
    )
    write_text_atomic(STARTWM, script, mode=0o755)
    run(["loginctl", "enable-linger", config.username])
    run(["systemctl", "start", f"user@{account.pw_uid}.service"])
    from common.agent_steps import install_agent_cli_launcher, install_managed_agent_skills

    install_agent_cli_launcher(config)
    install_managed_agent_skills(config.username, config.selected_agent_tools(), ("infra-tools-desktop",))
