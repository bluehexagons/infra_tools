"""Tests for xRDP login prerequisite validation."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import SetupConfig
from lib.validation import validate_rdp_settings


class TestValidateRdpSettings(unittest.TestCase):
    def test_rdp_policy_requires_rdp_to_be_enabled(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            rdp_allowed_sources=["10.0.0.0/24"],
        )

        with self.assertRaisesRegex(ValueError, "policy options require --rdp"):
            validate_rdp_settings(config)

    def test_rdp_requires_a_password(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
        )

        with self.assertRaisesRegex(ValueError, "--rdp requires --password"):
            validate_rdp_settings(config)

    def test_rdp_existing_password_accepts_existing_local_account(self) -> None:
        config = SetupConfig(
            host="localhost",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
        )

        with patch("lib.validation.pwd.getpwnam", return_value=object()), \
             patch(
                 "lib.validation.subprocess.run",
                 return_value=SimpleNamespace(
                     returncode=0,
                     stdout="agent P 2026-01-01\n",
                 ),
             ):
            validate_rdp_settings(config)

    def test_rdp_existing_password_rejects_locked_account(self) -> None:
        config = SetupConfig(
            host="localhost",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
        )

        with patch("lib.validation.pwd.getpwnam", return_value=object()), \
             patch(
                 "lib.validation.subprocess.run",
                 return_value=SimpleNamespace(
                     returncode=0,
                     stdout="agent L 2026-01-01\n",
                 ),
             ), \
             self.assertRaisesRegex(ValueError, "unlocked password"):
            validate_rdp_settings(config)

    def test_rdp_existing_password_rejects_passwordless_account(self) -> None:
        config = SetupConfig(
            host="localhost",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
        )

        with patch("lib.validation.pwd.getpwnam", return_value=object()), \
             patch(
                 "lib.validation.subprocess.run",
                 return_value=SimpleNamespace(
                     returncode=0,
                     stdout="agent NP 2026-01-01\n",
                 ),
             ), \
             self.assertRaisesRegex(ValueError, "unlocked password"):
            validate_rdp_settings(config)

    def test_rdp_existing_password_rejects_missing_local_account(self) -> None:
        config = SetupConfig(
            host="localhost",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
        )

        with patch("lib.validation.pwd.getpwnam", side_effect=KeyError("agent")):
            with self.assertRaisesRegex(ValueError, "existing local desktop account"):
                validate_rdp_settings(config)

    def test_rdp_existing_password_is_local_only(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
        )

        with self.assertRaisesRegex(ValueError, "local setup target"):
            validate_rdp_settings(config)

    def test_rdp_existing_password_cannot_be_combined_with_password(self) -> None:
        config = SetupConfig(
            host="localhost",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_existing_password=True,
            password="secret",
        )

        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            validate_rdp_settings(config)

    def test_rdp_accepts_a_non_root_user_with_password(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
        )

        validate_rdp_settings(config)

    def test_rdp_rejects_root(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="root",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
        )

        with self.assertRaisesRegex(ValueError, "cannot be used with the root"):
            validate_rdp_settings(config)

    def test_rdp_accepts_valid_bind_address_and_sources(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_bind_address="10.0.0.25",
            rdp_allowed_sources=["10.0.0.0/24", "2001:db8::10"],
        )

        validate_rdp_settings(config)

    def test_rdp_rejects_invalid_bind_address(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_bind_address="0.0.0.0; shutdown -h now",
        )

        with self.assertRaisesRegex(ValueError, "Invalid RDP bind address"):
            validate_rdp_settings(config)

    def test_rdp_rejects_invalid_or_duplicate_sources(self) -> None:
        invalid = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_allowed_sources=["10.0.0.0/24; bad"],
        )
        with self.assertRaisesRegex(ValueError, "Invalid RDP source"):
            validate_rdp_settings(invalid)

        duplicate = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_allowed_sources=["10.0.0.1/24", "10.0.0.0/24"],
        )
        with self.assertRaisesRegex(ValueError, "Duplicate RDP source"):
            validate_rdp_settings(duplicate)

    def test_rdp_accepts_bounded_session_lifecycle(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_max_sessions=2,
            rdp_kill_disconnected=True,
            rdp_disconnected_timeout=86400,
            rdp_idle_timeout=14400,
        )

        validate_rdp_settings(config)

    def test_rdp_rejects_unsafe_session_limits(self) -> None:
        for max_sessions in (0, 101):
            with self.subTest(max_sessions=max_sessions):
                config = SetupConfig(
                    host="agent-vm",
                    username="agent",
                    system_type="workstation_dev",
                    enable_rdp=True,
                    password="correct-horse-battery-staple",
                    rdp_max_sessions=max_sessions,
                )
                with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                    validate_rdp_settings(config)

        negative_idle = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_idle_timeout=-1,
        )
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            validate_rdp_settings(negative_idle)

    def test_rdp_disconnected_timeout_requires_explicit_cleanup(self) -> None:
        missing_timeout = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_kill_disconnected=True,
        )
        with self.assertRaisesRegex(ValueError, "requires a positive"):
            validate_rdp_settings(missing_timeout)

        ignored_timeout = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
            rdp_disconnected_timeout=86400,
        )
        with self.assertRaisesRegex(ValueError, "requires --rdp-kill-disconnected"):
            validate_rdp_settings(ignored_timeout)


if __name__ == "__main__":
    unittest.main()
