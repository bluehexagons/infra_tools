"""Tests for managed Syncthing CLI configuration and validation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.arg_parser import create_setup_argument_parser
from lib.cache import merge_setup_configs
from lib.config import SetupConfig


class SyncthingConfigTest(unittest.TestCase):
    def _config(self, **overrides: object) -> SetupConfig:
        values: dict[str, object] = {
            "host": "fileserver",
            "username": "agent",
            "system_type": "server_lite",
            "enable_syncthing": True,
        }
        values.update(overrides)
        return SetupConfig(**values)  # type: ignore[arg-type]

    def test_flag_defaults_admin_and_round_trips(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["fileserver", "agent", "--syncthing"])
        with patch("lib.system_utils.get_local_timezone", return_value="UTC"):
            config = SetupConfig.from_args(args, "server_lite")

        self.assertTrue(config.enable_syncthing)
        self.assertEqual(config.syncthing_admin, "syncthing-admin")
        self.assertIn("--syncthing", config.to_remote_args())
        self.assertIn("--syncthing-admin syncthing-admin", config.to_remote_args())

        restored = SetupConfig.from_dict("fileserver", "server_lite", config.to_dict())
        self.assertEqual(restored.syncthing_admin, "syncthing-admin")

    def test_custom_admin_is_in_commands(self) -> None:
        config = self._config(syncthing_admin="file-admin")

        self.assertIn("--syncthing-admin file-admin", config.to_remote_args())
        self.assertIn("--syncthing-admin file-admin", config.to_setup_command())

    def test_patch_omission_preserves_syncthing_settings(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["fileserver", "agent"])
        with patch("lib.system_utils.get_local_timezone", return_value="UTC"):
            update = SetupConfig.from_args(args, "server_lite")
        self.assertIsNone(update.enable_syncthing)
        self.assertIsNone(update.syncthing_admin)

        merged = merge_setup_configs(self._config(), update)
        self.assertTrue(merged.enable_syncthing)
        self.assertEqual(merged.syncthing_admin, "syncthing-admin")

    def test_explicit_disable_clears_admin(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["fileserver", "agent", "--no-syncthing"])
        with patch("lib.system_utils.get_local_timezone", return_value="UTC"):
            update = SetupConfig.from_args(args, "server_lite")

        merged = merge_setup_configs(self._config(), update)

        self.assertFalse(merged.enable_syncthing)
        self.assertTrue(merged.disable_syncthing)
        self.assertIsNone(merged.syncthing_admin)
        self.assertIn("--no-syncthing", merged.to_remote_args())
        self.assertNotIn("disable_syncthing", merged.to_dict())

    def test_removed_declarations_are_ignored_in_old_cache(self) -> None:
        data = self._config().to_dict()
        data.update(
            {
                "syncthing_devices": [["old-device", "OLD-ID"]],
                "syncthing_folders": [
                    ["send-receive", "old", "/srv/old", "old-device"]
                ],
                "syncthing_versioning": "trashcan",
            }
        )

        restored = SetupConfig.from_dict("fileserver", "server_lite", data)

        self.assertTrue(restored.enable_syncthing)
        self.assertFalse(hasattr(restored, "syncthing_devices"))

    def test_admin_requires_enablement_and_valid_username(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --syncthing"):
            self._config(enable_syncthing=False, syncthing_admin="file-admin")
        with self.assertRaisesRegex(ValueError, "valid username"):
            self._config(syncthing_admin="Not Valid")

    def test_root_and_oci_targets_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-root"):
            self._config(username="root")
        with self.assertRaisesRegex(ValueError, "OCI"):
            self._config(machine_type="oci")


if __name__ == "__main__":
    unittest.main()
