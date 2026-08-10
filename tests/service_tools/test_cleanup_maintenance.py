"""Tests for common.service_tools.cleanup_maintenance."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import cleanup_maintenance


class TestCleanupMaintenance(unittest.TestCase):
    @patch("common.service_tools.cleanup_maintenance.notify_if_storage_still_low")
    @patch("common.service_tools.cleanup_maintenance.cleanup_stale_crash_reports", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.cleanup_stale_infra_tmp_artifacts", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.run_optional_cleanup", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.cleanup_filesystem_free_space", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.cleanup_unused_packages", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.cleanup_apt_cache", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.load_notification_configs_from_state", return_value=[])
    def test_successful_cleanup_returns_zero(
        self,
        _configs,
        mock_apt,
        mock_unused_packages,
        mock_trim,
        mock_optional,
        mock_tmp_cleanup,
        mock_crash_cleanup,
        mock_low_space,
    ):
        with self.assertLogs(cleanup_maintenance.logger, level="INFO") as logs:
            result = cleanup_maintenance.main()
        self.assertEqual(result, 0)
        mock_apt.assert_called_once()
        mock_unused_packages.assert_called_once()
        mock_trim.assert_called_once()
        self.assertEqual(mock_optional.call_count, 6)
        self.assertFalse(any(call.args[2] == "gem cleanup" for call in mock_optional.call_args_list))
        # Stale infra tmp cleanup runs once per known temp directory (/tmp, /var/tmp).
        self.assertEqual(mock_tmp_cleanup.call_count, len(cleanup_maintenance.INFRA_TMP_DIRS))
        self.assertEqual(
            mock_crash_cleanup.call_count,
            len(cleanup_maintenance.CRASH_REPORT_DIRS),
        )
        mock_low_space.assert_called_once()
        joined = "\n".join(logs.output)
        self.assertIn("Starting cleanup maintenance", joined)
        self.assertIn("Cleanup maintenance completed successfully", joined)

    @patch("common.service_tools.cleanup_maintenance.notify_if_storage_still_low")
    @patch("common.service_tools.cleanup_maintenance.cleanup_stale_crash_reports", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.cleanup_stale_infra_tmp_artifacts", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.send_notification_safe")
    @patch(
        "common.service_tools.cleanup_maintenance.run_optional_cleanup",
        side_effect=[None, "journal vacuum: failed", None, None, None, None],
    )
    @patch("common.service_tools.cleanup_maintenance.cleanup_filesystem_free_space", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.cleanup_unused_packages", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.cleanup_apt_cache", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.load_notification_configs_from_state", return_value=["cfg"])
    def test_failure_notifies(
        self,
        _configs,
        _apt,
        _unused_packages,
        _trim,
        _optional,
        mock_notify,
        _tmp_cleanup,
        _crash_cleanup,
        mock_low_space,
    ):
        result = cleanup_maintenance.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("cleanup maintenance failed", mock_notify.call_args.kwargs["subject"])
        self.assertIn("journal vacuum: failed", mock_notify.call_args.kwargs["details"])
        mock_low_space.assert_called_once()


class TestCleanupHelpers(unittest.TestCase):
    @patch("common.service_tools.cleanup_maintenance.run_command")
    def test_run_cleanup_command_logs_structured_failure(self, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

        with self.assertLogs(cleanup_maintenance.logger, level="WARNING") as logs:
            failure = cleanup_maintenance.run_cleanup_command(["apt-get", "clean"], "APT clean")

        self.assertEqual(failure, "APT clean: permission denied")
        self.assertIn("APT clean failed | stderr='permission denied'", "\n".join(logs.output))

    @patch("common.service_tools.cleanup_maintenance.run_command")
    def test_run_cleanup_command_reports_timeout(self, mock_run_command):
        mock_run_command.side_effect = subprocess.TimeoutExpired(["journalctl"], timeout=600)

        with self.assertLogs(cleanup_maintenance.logger, level="WARNING") as logs:
            failure = cleanup_maintenance.run_cleanup_command(["journalctl"], "journal vacuum")

        self.assertEqual(failure, "journal vacuum: timed out after 600s")
        self.assertIn("journal vacuum timed out", "\n".join(logs.output))

    @patch("common.service_tools.cleanup_maintenance.run_command", side_effect=OSError("missing"))
    def test_run_cleanup_command_reports_os_error(self, _run_command):
        failure = cleanup_maintenance.run_cleanup_command(["missing"], "optional cleanup")

        self.assertEqual(failure, "optional cleanup: missing")

    @patch("common.service_tools.cleanup_maintenance.run_command")
    @patch(
        "common.service_tools.cleanup_maintenance.shutil.which",
        return_value="/usr/bin/apt-get",
    )
    def test_cleanup_apt_cache_uses_noninteractive_env(self, _which, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        cleanup_maintenance.cleanup_apt_cache()

        first_call = mock_run_command.call_args_list[0]
        self.assertEqual(
            first_call.args[0],
            ["/usr/bin/apt-get", "autoclean", "-qq", "-o", "DPkg::Lock::Timeout=300"],
        )
        self.assertEqual(first_call.kwargs["env"]["DEBIAN_FRONTEND"], "noninteractive")
        self.assertEqual(
            mock_run_command.call_args_list[1].args[0],
            ["/usr/bin/apt-get", "clean", "-o", "DPkg::Lock::Timeout=300"],
        )

    @patch("common.service_tools.cleanup_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.shutil.which", return_value="/usr/bin/apt-get")
    def test_cleanup_unused_packages_autoremoves_with_purge(
        self,
        _which,
        mock_cleanup,
    ):
        result = cleanup_maintenance.cleanup_unused_packages()

        self.assertEqual(result, [])
        self.assertEqual(mock_cleanup.call_count, 2)
        mock_cleanup.assert_any_call(
            [
                "/usr/bin/apt-get",
                "autoremove",
                "--purge",
                "-y",
                "-qq",
                "-o",
                "DPkg::Lock::Timeout=300",
            ],
            "APT unused package cleanup",
            env=mock_cleanup.call_args.kwargs["env"],
        )
        mock_cleanup.assert_any_call(
            [
                "/usr/bin/apt-get",
                "purge",
                "-y",
                "-qq",
                "~c",
                "-o",
                "DPkg::Lock::Timeout=300",
            ],
            "APT residual configuration cleanup",
            env=mock_cleanup.call_args.kwargs["env"],
        )
        self.assertEqual(
            mock_cleanup.call_args.kwargs["env"]["DEBIAN_FRONTEND"],
            "noninteractive",
        )

    @patch("common.service_tools.cleanup_maintenance.run_cleanup_command", return_value=None)
    @patch(
        "common.service_tools.cleanup_maintenance.shutil.which",
        return_value="/usr/bin/journalctl",
    )
    def test_journal_cleanup_rotates_and_enforces_age_and_size(self, _which, mock_cleanup):
        cleanup_maintenance.run_optional_cleanup(
            ["journalctl"],
            [
                "--rotate",
                f"--vacuum-size={cleanup_maintenance.JOURNAL_MAX_USE}",
                f"--vacuum-time={cleanup_maintenance.JOURNAL_MAX_AGE}",
            ],
            "journal rotation and vacuum",
        )

        mock_cleanup.assert_called_once_with(
            [
                "/usr/bin/journalctl",
                "--rotate",
                f"--vacuum-size={cleanup_maintenance.JOURNAL_MAX_USE}",
                f"--vacuum-time={cleanup_maintenance.JOURNAL_MAX_AGE}",
            ],
            "journal rotation and vacuum",
        )

    @patch("common.service_tools.cleanup_maintenance.run_cleanup_command", return_value=None)
    @patch(
        "common.service_tools.cleanup_maintenance.shutil.which",
        side_effect=[None, "/usr/bin/pip"],
    )
    def test_run_optional_cleanup_uses_first_available_executable(self, _which, mock_cleanup):
        result = cleanup_maintenance.run_optional_cleanup(
            ["pip3", "pip"],
            ["cache", "purge"],
            "pip cache cleanup",
        )

        self.assertIsNone(result)
        mock_cleanup.assert_called_once_with(
            ["/usr/bin/pip", "cache", "purge"],
            "pip cache cleanup",
        )

    @patch("common.service_tools.cleanup_maintenance.run_optional_cleanup", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.is_container", return_value=False)
    def test_cleanup_filesystem_free_space_trims_host(self, _is_container, mock_optional):
        result = cleanup_maintenance.cleanup_filesystem_free_space()

        self.assertIsNone(result)
        mock_optional.assert_called_once_with(
            ["fstrim"],
            ["--all", "--verbose", "--quiet-unsupported"],
            "filesystem trim",
        )

    @patch("common.service_tools.cleanup_maintenance.run_optional_cleanup")
    @patch("common.service_tools.cleanup_maintenance.is_container", return_value=True)
    def test_cleanup_filesystem_free_space_skips_container(
        self,
        _is_container,
        mock_optional,
    ):
        result = cleanup_maintenance.cleanup_filesystem_free_space()

        self.assertIsNone(result)
        mock_optional.assert_not_called()

    def test_cleanup_stale_crash_reports_removes_only_old_recognized_files(self):
        with tempfile.TemporaryDirectory() as crash_dir:
            old_core = os.path.join(crash_dir, "core.python.1000.boot.123.zst")
            old_apport = os.path.join(crash_dir, "_usr_bin_python3.1000.crash")
            fresh_core = os.path.join(crash_dir, "core.fresh.1000.boot.456.zst")
            unrelated = os.path.join(crash_dir, "operator-note.txt")
            old_directory = os.path.join(crash_dir, "core.directory")
            old_symlink = os.path.join(crash_dir, "core.symlink")
            for path in (old_core, old_apport, fresh_core, unrelated):
                with open(path, "w", encoding="utf-8") as file_obj:
                    file_obj.write("x")
            os.mkdir(old_directory)
            os.symlink(old_core, old_symlink)

            old_time = time.time() - (31 * 24 * 60 * 60)
            for path in (old_core, old_apport, unrelated, old_directory):
                os.utime(path, (old_time, old_time))

            failures = cleanup_maintenance.cleanup_stale_crash_reports(
                crash_dir=crash_dir,
                max_age_days=30,
            )

            self.assertEqual(failures, [])
            self.assertFalse(os.path.exists(old_core))
            self.assertFalse(os.path.exists(old_apport))
            self.assertTrue(os.path.exists(fresh_core))
            self.assertTrue(os.path.exists(unrelated))
            self.assertTrue(os.path.isdir(old_directory))
            self.assertTrue(os.path.islink(old_symlink))

    def test_cleanup_stale_crash_reports_reports_remove_failure(self):
        with tempfile.TemporaryDirectory() as crash_dir:
            old_core = os.path.join(crash_dir, "core.python.1000.boot.123.zst")
            with open(old_core, "w", encoding="utf-8") as file_obj:
                file_obj.write("x")
            old_time = time.time() - (31 * 24 * 60 * 60)
            os.utime(old_core, (old_time, old_time))

            with patch(
                "common.service_tools.cleanup_maintenance.os.unlink",
                side_effect=OSError("busy"),
            ):
                failures = cleanup_maintenance.cleanup_stale_crash_reports(
                    crash_dir=crash_dir,
                    max_age_days=30,
                )

            self.assertEqual(failures, [f"{old_core}: busy"])

    def test_cleanup_stale_infra_tmp_artifacts_removes_only_old_owned_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_dir = os.path.join(tmp_dir, "infra_setup_build_abcd")
            old_file = os.path.join(tmp_dir, "antistatic-server-linux-amd64.v1")
            old_bundler_dir = os.path.join(tmp_dir, "bundler20240101-12345-abc123")
            fresh_file = os.path.join(tmp_dir, "infra_deploy_fresh")
            unrelated_file = os.path.join(tmp_dir, "unrelated")
            misleading_file = os.path.join(tmp_dir, "bundler_project")
            os.mkdir(old_dir)
            os.mkdir(old_bundler_dir)
            for path in (old_file, fresh_file, unrelated_file, misleading_file):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("x")

            old_time = time.time() - (8 * 24 * 60 * 60)
            os.utime(old_dir, (old_time, old_time))
            os.utime(old_bundler_dir, (old_time, old_time))
            os.utime(old_file, (old_time, old_time))
            os.utime(misleading_file, (old_time, old_time))

            failures = cleanup_maintenance.cleanup_stale_infra_tmp_artifacts(
                tmp_dir=tmp_dir,
                max_age_days=7,
            )

            self.assertEqual(failures, [])
            self.assertFalse(os.path.exists(old_dir))
            self.assertFalse(os.path.exists(old_bundler_dir))
            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(fresh_file))
            self.assertTrue(os.path.exists(unrelated_file))
            self.assertTrue(os.path.exists(misleading_file))

    def test_cleanup_stale_infra_tmp_artifacts_reports_remove_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_dir = os.path.join(tmp_dir, "infra_recall_abcd")
            os.mkdir(old_dir)
            old_time = time.time() - (8 * 24 * 60 * 60)
            os.utime(old_dir, (old_time, old_time))

            with patch(
                "common.service_tools.cleanup_maintenance.shutil.rmtree",
                side_effect=OSError("busy"),
            ):
                failures = cleanup_maintenance.cleanup_stale_infra_tmp_artifacts(
                    tmp_dir=tmp_dir,
                    max_age_days=7,
                )

            self.assertEqual(failures, [f"{old_dir}: busy"])

    @patch("common.service_tools.cleanup_maintenance.send_notification_safe")
    @patch("common.service_tools.cleanup_maintenance.get_disk_usage_details", return_value={
        "total_mb": 1000,
        "used_mb": 920,
        "free_mb": 80,
        "usage_percent": 92,
    })
    def test_low_space_notification_sends_warning(self, _usage, mock_notify):
        cleanup_maintenance.notify_if_storage_still_low(["cfg"])

        mock_notify.assert_called_once()
        self.assertIn("storage still low after cleanup", mock_notify.call_args.kwargs["subject"].lower())
        self.assertEqual(mock_notify.call_args.kwargs["status"], "error")

    @patch("common.service_tools.cleanup_maintenance.send_notification_safe")
    @patch("common.service_tools.cleanup_maintenance.get_disk_usage_details", return_value={
        "total_mb": 1000,
        "used_mb": 700,
        "free_mb": 300,
        "usage_percent": 70,
    })
    def test_low_space_notification_skips_when_usage_is_ok(self, _usage, mock_notify):
        cleanup_maintenance.notify_if_storage_still_low([])

        mock_notify.assert_not_called()

    @patch("common.service_tools.cleanup_maintenance.shutil.disk_usage")
    def test_log_tmp_usage_logs_stats(self, mock_usage):
        from collections import namedtuple
        DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
        mock_usage.return_value = DiskUsage(
            total=10 * 1024 * 1024 * 1024,
            used=2 * 1024 * 1024 * 1024,
            free=8 * 1024 * 1024 * 1024,
        )
        with self.assertLogs(cleanup_maintenance.logger, level="DEBUG") as logs:
            cleanup_maintenance.log_tmp_usage("/tmp")
        joined = "\n".join(logs.output)
        self.assertIn("Temp directory usage", joined)
        self.assertIn("tmp_dir='/tmp'", joined)

    @patch("common.service_tools.cleanup_maintenance.shutil.disk_usage", side_effect=OSError("no such directory"))
    def test_log_tmp_usage_handles_oserror(self, _mock_usage):
        with self.assertLogs(cleanup_maintenance.logger, level="WARNING") as logs:
            cleanup_maintenance.log_tmp_usage("/nonexistent")
        self.assertIn("Could not read temp directory usage", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
