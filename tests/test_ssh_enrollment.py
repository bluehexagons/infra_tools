"""Tests for explicit SSH host-key enrollment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.ssh_enrollment import enroll_host_key, replace_scanned_host_keys


class TestSshEnrollment(unittest.TestCase):
    @patch("lib.ssh_enrollment.get_workspace_known_hosts_path")
    @patch("lib.ssh_enrollment.subprocess.run")
    def test_enrolls_after_noninteractive_confirmation(self, run, known_hosts):
        run.side_effect = [
            type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "example.com ssh-ed25519 AAAA",
                    "stderr": "",
                },
            )(),
            type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "256 SHA256:fingerprint host (ED25519)",
                    "stderr": "",
                },
            )(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "known_hosts"
            known_hosts.return_value = str(path)
            self.assertEqual(enroll_host_key("example.com", assume_yes=True), 0)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "example.com ssh-ed25519 AAAA\n",
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                run.call_args_list[0].args[0],
                [
                    "ssh-keyscan",
                    "-T",
                    "10",
                    "-t",
                    "ed25519",
                    "-p",
                    "22",
                    "example.com",
                ],
            )

    @patch("lib.ssh_enrollment.subprocess.run")
    def test_decline_does_not_write_key(self, run):
        run.side_effect = [
            type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "example.com ssh-ed25519 AAAA",
                    "stderr": "",
                },
            )(),
            type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "256 SHA256:fingerprint host (ED25519)",
                    "stderr": "",
                },
            )(),
        ]
        with patch("lib.ssh_enrollment.get_workspace_known_hosts_path") as known_hosts:
            known_hosts.return_value = "/tmp/should-not-be-written"
            self.assertEqual(enroll_host_key("example.com", input_fn=lambda _: "n"), 1)

    @patch("lib.ssh_enrollment.get_workspace_known_hosts_path")
    @patch("lib.ssh_enrollment.subprocess.run")
    def test_replace_removes_a_stale_host_key(self, run, known_hosts):
        old_key = "192.0.2.40 ssh-ed25519 OLD"
        new_key = "192.0.2.40 ssh-ed25519 NEW"
        run.side_effect = [
            type(
                "Result",
                (),
                {"returncode": 0, "stdout": "256 SHA256:new", "stderr": ""},
            )(),
            type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": f"# Host 192.0.2.40 found: line 1\n{old_key}\n",
                    "stderr": "",
                },
            )(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "known_hosts"
            path.write_text(old_key + "\nother ssh-ed25519 KEEP\n", encoding="utf-8")
            known_hosts.return_value = str(path)

            self.assertEqual(
                replace_scanned_host_keys("192.0.2.40", new_key),
                str(path),
            )

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "other ssh-ed25519 KEEP\n" + new_key + "\n",
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @patch("lib.ssh_enrollment.subprocess.run")
    def test_replace_rejects_a_scan_for_another_host(self, run):
        with self.assertRaisesRegex(RuntimeError, "unexpected host"):
            replace_scanned_host_keys(
                "192.0.2.40",
                "192.0.2.41 ssh-ed25519 AAAA",
            )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
