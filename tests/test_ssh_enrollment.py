"""Tests for explicit SSH host-key enrollment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.ssh_enrollment import enroll_host_key


class TestSshEnrollment(unittest.TestCase):
    @patch("lib.ssh_enrollment.get_workspace_known_hosts_path")
    @patch("lib.ssh_enrollment.subprocess.run")
    def test_enrolls_after_noninteractive_confirmation(self, run, known_hosts):
        run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": "host ssh-ed25519 AAAA", "stderr": ""})(),
            type("Result", (), {"returncode": 0, "stdout": "256 SHA256:fingerprint host (ED25519)", "stderr": ""})(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "known_hosts"
            known_hosts.return_value = str(path)
            self.assertEqual(enroll_host_key("example.com", assume_yes=True), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "host ssh-ed25519 AAAA\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @patch("lib.ssh_enrollment.subprocess.run")
    def test_decline_does_not_write_key(self, run):
        run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": "host ssh-ed25519 AAAA", "stderr": ""})(),
            type("Result", (), {"returncode": 0, "stdout": "256 SHA256:fingerprint host (ED25519)", "stderr": ""})(),
        ]
        with patch("lib.ssh_enrollment.get_workspace_known_hosts_path") as known_hosts:
            known_hosts.return_value = "/tmp/should-not-be-written"
            self.assertEqual(enroll_host_key("example.com", input_fn=lambda _: "n"), 1)


if __name__ == "__main__":
    unittest.main()
