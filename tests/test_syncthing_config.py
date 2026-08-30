"""Tests for managed Syncthing CLI configuration and validation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig


REMOTE_DEVICE_ID = (
    "S7UKX27-GI7ZTXS-GC6RKUA-7AJGZ44-C6NAYEB-HSKTJQK-KJHU2NO-CWV7EQW"
)


class SyncthingConfigTest(unittest.TestCase):
    def _config(self, **overrides: object) -> SetupConfig:
        values: dict[str, object] = {
            "host": "fileserver",
            "username": "agent",
            "system_type": "server_lite",
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

    def test_flags_auto_enable_and_round_trip(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            [
                "fileserver",
                "agent",
                "--syncthing-device",
                "alice-laptop",
                REMOTE_DEVICE_ID,
                "--syncthing-folder",
                "send-receive",
                "shared-work",
                "/srv/syncthing/shared-work",
                "alice-laptop",
                "--syncthing-versioning",
                "trashcan",
            ]
        )
        with patch("lib.system_utils.get_local_timezone", return_value="UTC"):
            config = SetupConfig.from_args(args, "server_lite")

        self.assertTrue(config.enable_syncthing)
        self.assertEqual(config.syncthing_versioning, "trashcan")
        self.assertIn("--syncthing", config.to_remote_args())
        self.assertIn(
            f"--syncthing-device alice-laptop {REMOTE_DEVICE_ID}",
            config.to_remote_args(),
        )
        self.assertIn(
            "--syncthing-folder send-receive shared-work "
            "/srv/syncthing/shared-work alice-laptop",
            config.to_setup_command(),
        )

        restored = SetupConfig.from_dict(
            "fileserver", "server_lite", config.to_dict()
        )
        self.assertEqual(restored.syncthing_devices, config.syncthing_devices)
        self.assertEqual(restored.syncthing_folders, config.syncthing_folders)

    def test_default_staggered_versioning_is_implicit_in_commands(self) -> None:
        config = self._config()
        self.assertNotIn(
            "--syncthing-versioning staggered", config.to_remote_args()
        )
        self.assertNotIn(
            "--syncthing-versioning staggered", config.to_setup_command()
        )

    def test_folder_must_reference_a_declared_device(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown device.*bob-laptop"):
            self._config(
                syncthing_folders=[
                    [
                        "send-receive",
                        "shared-work",
                        "/srv/syncthing/shared-work",
                        "bob-laptop",
                    ]
                ]
            )

    def test_folder_path_is_limited_to_data_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "PATH must be below"):
            self._config(
                syncthing_folders=[
                    ["send-receive", "shared-work", "/etc/shared", "alice-laptop"]
                ]
            )

    def test_full_device_id_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "full uppercase"):
            self._config(syncthing_devices=[["alice-laptop", "S7UKX27"]])

    def test_root_and_oci_targets_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-root"):
            self._config(username="root")
        with self.assertRaisesRegex(ValueError, "OCI"):
            self._config(machine_type="oci")


if __name__ == "__main__":
    unittest.main()
