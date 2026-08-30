"""Managed Syncthing endpoint installation and declarative configuration."""

from __future__ import annotations

import copy
import grp
import json
import os
import pwd
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lib.atomic_io import write_text_atomic
from lib.config import SetupConfig
from lib.machine_state import can_manage_system_services
from lib.remote_utils import is_dry_run, is_package_installed, run


SYNCTHING_HOME = "/var/lib/infra-tools/syncthing"
SYNCTHING_CONFIG_FILE = os.path.join(SYNCTHING_HOME, "config.xml")
SYNCTHING_SERVICE_NAME = "infra-syncthing"
SYNCTHING_SERVICE_FILE = (
    f"/etc/systemd/system/{SYNCTHING_SERVICE_NAME}.service"
)
SYNCTHING_GUI_ADDRESS = "127.0.0.1:8384"
SYNCTHING_API_URL = f"http://{SYNCTHING_GUI_ADDRESS}/rest/config"
_DEVICE_ID_PATTERN = re.compile(r"^[A-Z2-7]{7}(?:-[A-Z2-7]{7}){7}$")
_FOLDER_TYPE = {
    "send-receive": "sendreceive",
    "send-only": "sendonly",
    "receive-only": "receiveonly",
}


def _account(username: str) -> tuple[int, int, str]:
    """Return the target user's UID, GID, and primary group name."""

    try:
        account = pwd.getpwnam(username)
        group_name = grp.getgrgid(account.pw_gid).gr_name
    except KeyError as exc:
        raise RuntimeError(f"Syncthing setup user does not exist: {username}") from exc
    return account.pw_uid, account.pw_gid, group_name


def _systemd_quote(value: str) -> str:
    """Quote one validated path for a systemd unit directive."""

    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _render_service(config: SetupConfig, group_name: str) -> str:
    """Render the hardened system service for the selected setup account."""

    writable_paths = [SYNCTHING_HOME]
    writable_paths.extend(spec[2] for spec in config.syncthing_folders or [])
    writable_lines = "\n".join(
        f"ReadWritePaths={_systemd_quote(path)}"
        for path in dict.fromkeys(writable_paths)
    )
    return f"""[Unit]
Description=Managed Syncthing file synchronization
Documentation=https://docs.syncthing.net/
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={config.username}
Group={group_name}
UMask=0007
ExecStart=/usr/bin/syncthing serve --home={SYNCTHING_HOME} --gui-address=http://{SYNCTHING_GUI_ADDRESS} --no-browser --no-restart --no-upgrade
Restart=on-failure
RestartSec=5s
SuccessExitStatus=3 4
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectClock=true
ProtectControlGroups=true
ProtectHome=read-only
ProtectHostname=true
ProtectKernelLogs=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
{writable_lines}

[Install]
WantedBy=multi-user.target
"""


def _run_as_user(
    username: str,
    syncthing_args: list[str],
    *,
    capture_output: bool = False,
    check: bool = True,
) -> Any:
    """Run the packaged Syncthing binary as its unprivileged service user."""

    return run(
        ["runuser", "-u", username, "--", "/usr/bin/syncthing", *syncthing_args],
        capture_output=capture_output,
        check=check,
    )


def _cli(
    username: str,
    arguments: list[str],
    *,
    capture_output: bool = False,
    check: bool = True,
) -> Any:
    return _run_as_user(
        username,
        ["cli", f"--home={SYNCTHING_HOME}", *arguments],
        capture_output=capture_output,
        check=check,
    )


def _wait_for_api(username: str, attempts: int = 30) -> None:
    """Wait briefly for the loopback-only Syncthing API to become ready."""

    for _attempt in range(attempts):
        result = _cli(
            username,
            ["show", "system"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("Syncthing API did not become ready on 127.0.0.1:8384")


def _load_current_config(username: str) -> dict[str, Any]:
    """Read the active config through Syncthing's version-aware CLI."""

    result = _cli(
        username,
        ["config", "dump-json"],
        capture_output=True,
    )
    try:
        loaded = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Syncthing returned an invalid configuration") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError("Syncthing returned a non-object configuration")
    return loaded


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Syncthing configuration is missing {name}")
    return copy.deepcopy(value)


def _versioning_config(default: object, mode: str) -> dict[str, Any]:
    versioning = _mapping(default, "folder versioning defaults")
    versioning["cleanupIntervalS"] = 3600
    versioning["fsPath"] = ""
    versioning["fsType"] = "basic"
    if mode == "none":
        versioning["type"] = ""
        versioning["params"] = {}
    elif mode == "trashcan":
        versioning["type"] = "trashcan"
        versioning["params"] = {"cleanoutDays": "30"}
    else:
        versioning["type"] = "staggered"
        versioning["params"] = {
            "cleanInterval": "3600",
            "maxAge": "31536000",
        }
    return versioning


def build_managed_syncthing_config(
    current: dict[str, Any],
    config: SetupConfig,
    local_device_id: str,
) -> dict[str, Any]:
    """Build a full desired config while retaining installed-version defaults."""

    if not _DEVICE_ID_PATTERN.fullmatch(local_device_id):
        raise RuntimeError("Syncthing returned an invalid local device ID")

    current_devices = current.get("devices")
    if not isinstance(current_devices, list):
        raise RuntimeError("Syncthing configuration is missing devices")
    local_device = next(
        (
            copy.deepcopy(device)
            for device in current_devices
            if isinstance(device, dict)
            and device.get("deviceID") == local_device_id
        ),
        None,
    )
    if local_device is None:
        raise RuntimeError("Syncthing configuration does not contain its local device")

    defaults = _mapping(current.get("defaults"), "defaults")
    default_device = _mapping(defaults.get("device"), "device defaults")
    default_folder = _mapping(defaults.get("folder"), "folder defaults")
    device_ids = {
        name: device_id
        for name, device_id in config.syncthing_devices or []
    }
    if local_device_id in device_ids.values():
        raise RuntimeError("A remote Syncthing device ID matches this endpoint")

    desired = copy.deepcopy(current)
    desired_devices = [local_device]
    for name, device_id in config.syncthing_devices or []:
        device = copy.deepcopy(default_device)
        device.update(
            {
                "deviceID": device_id,
                "name": name,
                "addresses": ["dynamic"],
                "compression": "metadata",
                "introducer": False,
                "skipIntroductionRemovals": False,
                "introducedBy": "",
                "paused": False,
                "autoAcceptFolders": False,
                "untrusted": False,
            }
        )
        desired_devices.append(device)
    desired["devices"] = desired_devices

    desired_folders: list[dict[str, Any]] = []
    for mode, folder_id, path, raw_devices in config.syncthing_folders or []:
        folder = copy.deepcopy(default_folder)
        folder_device_ids = [
            device_ids[name.strip()] for name in raw_devices.split(",")
        ]
        folder.update(
            {
                "id": folder_id,
                "label": folder_id,
                "filesystemType": "basic",
                "path": path,
                "type": _FOLDER_TYPE[mode],
                "devices": [
                    {
                        "deviceID": device_id,
                        "introducedBy": "",
                        "encryptionPassword": "",
                    }
                    for device_id in [local_device_id, *folder_device_ids]
                ],
                "rescanIntervalS": 3600,
                "fsWatcherEnabled": True,
                "fsWatcherDelayS": 10,
                "ignorePerms": False,
                "autoNormalize": True,
                "minDiskFree": {"value": 1, "unit": "%"},
                "maxConflicts": 10,
                "disableFsync": False,
                "versioning": _versioning_config(
                    default_folder.get("versioning"),
                    config.syncthing_versioning or "staggered",
                ),
            }
        )
        desired_folders.append(folder)
    desired["folders"] = desired_folders

    gui = _mapping(desired.get("gui"), "GUI settings")
    gui.update(
        {
            "enabled": True,
            "address": SYNCTHING_GUI_ADDRESS,
            "useTLS": False,
            "debugging": False,
            "insecureAdminAccess": False,
            "insecureSkipHostcheck": False,
            "insecureAllowFrameLoading": False,
        }
    )
    desired["gui"] = gui

    options = _mapping(desired.get("options"), "options")
    options.update(
        {
            "startBrowser": False,
            "globalAnnounceEnabled": True,
            "localAnnounceEnabled": True,
            "relaysEnabled": True,
            "natEnabled": False,
            "urAccepted": -1,
            "crashReportingEnabled": False,
        }
    )
    desired["options"] = options
    return desired


def _put_config(desired: dict[str, Any]) -> None:
    """Submit the desired config for atomic validation and replacement."""

    gui = desired.get("gui")
    api_key = gui.get("apiKey") if isinstance(gui, dict) else None
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError("Syncthing configuration does not contain an API key")
    request = Request(
        SYNCTHING_API_URL,
        data=json.dumps(desired, separators=(",", ":")).encode("utf-8"),
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status not in {200, 204}:
                raise RuntimeError(
                    f"Syncthing rejected its managed config (HTTP {response.status})"
                )
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"Syncthing rejected its managed config (HTTP {exc.code}){suffix}"
        ) from exc
    except URLError as exc:
        raise RuntimeError("Could not reach the loopback Syncthing API") from exc


def _prepare_folder_paths(config: SetupConfig, group_name: str) -> None:
    """Create missing share roots and verify service-user write access."""

    for _mode, _folder_id, path, _devices in config.syncthing_folders or []:
        if os.path.realpath(path) != path:
            raise RuntimeError(
                f"Syncthing folder path must not traverse symbolic links: {path}"
            )
        if os.path.exists(path):
            if not os.path.isdir(path):
                raise RuntimeError(f"Syncthing folder path is not a directory: {path}")
        else:
            run(
                [
                    "install",
                    "-d",
                    "-m",
                    "0770",
                    "-o",
                    config.username,
                    "-g",
                    group_name,
                    path,
                ]
            )
        writable = run(
            ["runuser", "-u", config.username, "--", "test", "-w", path],
            check=False,
        )
        if writable.returncode != 0:
            raise RuntimeError(
                f"Syncthing setup user cannot write folder path: {path}"
            )


def setup_syncthing(config: SetupConfig, **_kwargs: Any) -> None:
    """Install and reconcile one unprivileged, relay-capable Syncthing endpoint."""

    if not config.enable_syncthing:
        return
    if not can_manage_system_services(config.machine_type):
        print("  ✓ Skipping Syncthing (persistent services unavailable)")
        return
    if is_dry_run():
        print("  [DRY-RUN] Skipping Syncthing service configuration")
        return

    if not is_package_installed("syncthing"):
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run(
            [
                "apt-get",
                "-o",
                "DPkg::Lock::Timeout=60",
                "install",
                "-y",
                "-qq",
                "syncthing",
            ]
        )
        if not is_package_installed("syncthing"):
            raise RuntimeError("Syncthing package installation did not verify")

    uid, gid, group_name = _account(config.username)
    os.makedirs(SYNCTHING_HOME, mode=0o700, exist_ok=True)
    os.chmod(SYNCTHING_HOME, 0o700)
    os.chown(SYNCTHING_HOME, uid, gid)
    _prepare_folder_paths(config, group_name)

    if not os.path.exists(SYNCTHING_CONFIG_FILE):
        _run_as_user(
            config.username,
            [
                "generate",
                f"--home={SYNCTHING_HOME}",
                "--skip-port-probing",
                "--no-default-folder",
            ],
        )

    write_text_atomic(
        SYNCTHING_SERVICE_FILE,
        _render_service(config, group_name),
        mode=0o644,
    )
    run(["systemd-analyze", "verify", SYNCTHING_SERVICE_FILE])
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", f"{SYNCTHING_SERVICE_NAME}.service"])
    _wait_for_api(config.username)

    device_id_result = _run_as_user(
        config.username,
        ["serve", "--device-id", f"--home={SYNCTHING_HOME}"],
        capture_output=True,
    )
    local_device_id = str(device_id_result.stdout or "").strip()
    current = _load_current_config(config.username)
    desired = build_managed_syncthing_config(current, config, local_device_id)
    _put_config(desired)

    run(["systemctl", "restart", f"{SYNCTHING_SERVICE_NAME}.service"])
    _wait_for_api(config.username)
    active = run(
        ["systemctl", "is-active", f"{SYNCTHING_SERVICE_NAME}.service"],
        capture_output=True,
        check=False,
    )
    if active.returncode != 0:
        raise RuntimeError("Managed Syncthing service is not active")

    print(f"  ✓ Syncthing device ID: {local_device_id}")
    print("  ✓ Syncthing admin UI: http://127.0.0.1:8384 (loopback only)")
    print(
        "  ℹ Remote access: ssh -L 8384:127.0.0.1:8384 "
        f"{config.username}@{config.host}"
    )
    print("  ℹ No firewall or router mapping was added; relay fallback remains enabled")
