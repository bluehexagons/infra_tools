"""Tests for managed Syncthing service composition and config generation."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
from sync.syncthing_steps import (
    SYNCTHING_HOME,
    _render_service,
    build_managed_syncthing_config,
    setup_syncthing,
)


LOCAL_DEVICE_ID = (
    "BJ5ID3D-3BL2IM7-KPTHNB3-LI3SO5N-KDCFYJN-Z4HKBUQ-AIANLCB-LJOJXAT"
)
REMOTE_DEVICE_ID = (
    "S7UKX27-GI7ZTXS-GC6RKUA-7AJGZ44-C6NAYEB-HSKTJQK-KJHU2NO-CWV7EQW"
)


def _config(system_type: str = "server_lite", **overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "fileserver",
        "username": "agent",
        "system_type": system_type,
        "enable_syncthing": True,
        "syncthing_devices": [["alice-laptop", REMOTE_DEVICE_ID]],
        "syncthing_folders": [
            [
                "send-receive",
                "shared-work",
                "/srv/syncthing/shared-work",
                "alice-laptop",
            ]
        ],
    }
    values.update(overrides)
    return SetupConfig(**values)  # type: ignore[arg-type]


def _current_config() -> dict[str, object]:
    return {
        "version": 37,
        "folders": [],
        "devices": [
            {
                "deviceID": LOCAL_DEVICE_ID,
                "name": "fileserver",
                "addresses": ["dynamic"],
            }
        ],
        "gui": {
            "enabled": True,
            "address": "0.0.0.0:8384",
            "apiKey": "test-api-key",
            "useTLS": True,
        },
        "options": {
            "startBrowser": True,
            "relaysEnabled": False,
            "crashReportingEnabled": True,
        },
        "defaults": {
            "device": {
                "deviceID": "",
                "name": "",
                "addresses": ["dynamic"],
                "introducer": False,
            },
            "folder": {
                "id": "",
                "label": "",
                "path": "~",
                "type": "sendreceive",
                "devices": [{"deviceID": LOCAL_DEVICE_ID}],
                "versioning": {
                    "type": "",
                    "params": {},
                    "cleanupIntervalS": 3600,
                    "fsPath": "",
                    "fsType": "basic",
                },
                "maxConflicts": 10,
            },
        },
    }


class SyncthingDesiredConfigTest(unittest.TestCase):
    def test_builds_hub_folder_with_safe_network_and_gui_defaults(self) -> None:
        desired = build_managed_syncthing_config(
            _current_config(), _config(), LOCAL_DEVICE_ID
        )

        self.assertEqual(
            [device["deviceID"] for device in desired["devices"]],
            [LOCAL_DEVICE_ID, REMOTE_DEVICE_ID],
        )
        self.assertFalse(desired["devices"][1]["introducer"])
        folder = desired["folders"][0]
        self.assertEqual(folder["type"], "sendreceive")
        self.assertEqual(
            [device["deviceID"] for device in folder["devices"]],
            [LOCAL_DEVICE_ID, REMOTE_DEVICE_ID],
        )
        self.assertEqual(folder["versioning"]["type"], "staggered")
        self.assertEqual(folder["versioning"]["params"]["maxAge"], "31536000")
        self.assertEqual(desired["gui"]["address"], "127.0.0.1:8384")
        self.assertFalse(desired["gui"]["useTLS"])
        self.assertTrue(desired["options"]["relaysEnabled"])
        self.assertFalse(desired["options"]["natEnabled"])
        self.assertEqual(desired["options"]["urAccepted"], -1)
        self.assertFalse(desired["options"]["crashReportingEnabled"])

    def test_maps_folder_directions_and_versioning_modes(self) -> None:
        cases = (
            ("send-only", "sendonly", "trashcan", "trashcan"),
            ("receive-only", "receiveonly", "none", ""),
        )
        for mode, expected_type, versioning, expected_versioning in cases:
            with self.subTest(mode=mode, versioning=versioning):
                config = _config(
                    syncthing_folders=[
                        [
                            mode,
                            "shared-work",
                            "/srv/syncthing/shared-work",
                            "alice-laptop",
                        ]
                    ],
                    syncthing_versioning=versioning,
                )
                desired = build_managed_syncthing_config(
                    _current_config(), config, LOCAL_DEVICE_ID
                )
                self.assertEqual(desired["folders"][0]["type"], expected_type)
                self.assertEqual(
                    desired["folders"][0]["versioning"]["type"],
                    expected_versioning,
                )

    def test_rejects_declaring_the_local_device_as_a_peer(self) -> None:
        config = _config(
            syncthing_devices=[["this-server", LOCAL_DEVICE_ID]],
            syncthing_folders=[
                [
                    "send-receive",
                    "shared-work",
                    "/srv/syncthing/shared-work",
                    "this-server",
                ]
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "matches this endpoint"):
            build_managed_syncthing_config(
                _current_config(), config, LOCAL_DEVICE_ID
            )

    def test_service_is_unprivileged_hardened_and_loopback_only(self) -> None:
        service = _render_service(_config(), "agent")
        self.assertIn("User=agent", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("CapabilityBoundingSet=", service)
        self.assertIn("--gui-address=http://127.0.0.1:8384", service)
        self.assertIn(f'ReadWritePaths="{SYNCTHING_HOME}"', service)
        self.assertIn(
            'ReadWritePaths="/srv/syncthing/shared-work"', service
        )


class SyncthingCompositionTest(unittest.TestCase):
    def test_server_and_workstation_compositions_include_syncthing(self) -> None:
        for system_type in ("server_lite", "workstation_desktop"):
            with self.subTest(system_type=system_type):
                step_names = [
                    name for name, _step in get_steps_for_system_type(_config(system_type))
                ]
                self.assertIn("Configuring managed Syncthing endpoint", step_names)

    def test_disable_composition_removes_service_and_preserves_state(self) -> None:
        config = _config(
            enable_syncthing=False,
            disable_syncthing=True,
            syncthing_devices=None,
            syncthing_folders=None,
        )
        step_names = [
            name for name, _step in get_steps_for_system_type(config)
        ]
        self.assertIn("Removing managed Syncthing endpoint", step_names)

        with (
            patch("sync.syncthing_steps.can_manage_system_services", return_value=True),
            patch("sync.syncthing_steps.is_dry_run", return_value=False),
            patch("sync.syncthing_steps.os.path.lexists", return_value=True),
            patch("sync.syncthing_steps.os.path.islink", return_value=False),
            patch("sync.syncthing_steps.os.path.isfile", return_value=True),
            patch("sync.syncthing_steps.os.unlink") as unlink,
            patch("sync.syncthing_steps.run") as run_command,
        ):
            run_command.return_value = subprocess.CompletedProcess(
                args=[], returncode=3, stdout="inactive\n", stderr=""
            )
            setup_syncthing(config)

        unlink.assert_called_once()
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertIn(
            ["systemctl", "disable", "--now", "infra-syncthing.service"],
            commands,
        )
        self.assertIn(
            ["systemctl", "is-active", "--quiet", "infra-syncthing.service"],
            commands,
        )
        self.assertIn(["systemctl", "daemon-reload"], commands)

    def test_disable_refuses_to_remove_unit_while_service_is_active(self) -> None:
        config = _config(
            enable_syncthing=False,
            disable_syncthing=True,
            syncthing_devices=None,
            syncthing_folders=None,
        )
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="active\n", stderr=""
        )
        with (
            patch("sync.syncthing_steps.can_manage_system_services", return_value=True),
            patch("sync.syncthing_steps.is_dry_run", return_value=False),
            patch("sync.syncthing_steps.os.path.lexists", return_value=True),
            patch("sync.syncthing_steps.os.path.islink", return_value=False),
            patch("sync.syncthing_steps.os.path.isfile", return_value=True),
            patch("sync.syncthing_steps.os.unlink") as unlink,
            patch("sync.syncthing_steps.run", return_value=completed),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not stop"):
                setup_syncthing(config)

        unlink.assert_not_called()

    def test_setup_reconciles_through_the_validated_api(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=LOCAL_DEVICE_ID + "\n", stderr=""
        )
        current = _current_config()
        with (
            patch("sync.syncthing_steps.can_manage_system_services", return_value=True),
            patch("sync.syncthing_steps.is_dry_run", return_value=False),
            patch("sync.syncthing_steps.is_package_installed", return_value=True),
            patch("sync.syncthing_steps._account", return_value=(1000, 1000, "agent")),
            patch("sync.syncthing_steps.os.makedirs"),
            patch("sync.syncthing_steps.os.chmod"),
            patch("sync.syncthing_steps.os.chown"),
            patch("sync.syncthing_steps.os.path.exists", return_value=True),
            patch("sync.syncthing_steps._prepare_folder_paths"),
            patch("sync.syncthing_steps.write_text_atomic"),
            patch("sync.syncthing_steps.run") as run_command,
            patch("sync.syncthing_steps._wait_for_api"),
            patch("sync.syncthing_steps._run_as_user", return_value=completed),
            patch("sync.syncthing_steps._load_current_config", return_value=current),
            patch("sync.syncthing_steps._put_config") as put_config,
        ):
            run_command.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="active\n", stderr=""
            )
            setup_syncthing(_config())

        desired = put_config.call_args.args[0]
        self.assertEqual(desired["folders"][0]["id"], "shared-work")
        self.assertEqual(desired["devices"][1]["name"], "alice-laptop")


if __name__ == "__main__":
    unittest.main()
