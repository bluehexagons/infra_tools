"""Tests for Gogs operator commands."""

from __future__ import annotations

import argparse
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from lib.gogs_cli import (
    _format_health,
    _remote_health_script,
    add_gogs_subparser,
    inspect_remote_gogs,
    run_gogs_command,
)


def _healthy_result() -> dict[str, object]:
    return {
        "healthy": True,
        "service_active": True,
        "sqlite_healthy": True,
        "storage": {
            "source": "/dev/vdb1",
            "filesystem": "ext4",
            "mount_target": "/srv/gogs",
            "free_bytes": 2_000_000_000,
            "free_inodes": 20_000,
            "usage_bytes": {"repositories": 100, "lfs_objects": 200},
        },
        "update_job": {"failed": False},
        "update_timer": {"active": True},
        "update_check": {"age_seconds": 60, "stale": False, "successful": True},
        "nginx_upload_limit_bytes": 536_870_912,
        "nginx": {"required": True, "active": True, "config_valid": True},
        "frontend": {"healthy": True, "mode": "tls"},
        "remote_lfs_endpoint_configured": True,
    }


class TestGogsHealthParser(unittest.TestCase):
    def test_parser_accepts_json_and_capacity_thresholds(self):
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command")
        add_gogs_subparser(commands)

        args = parser.parse_args(
            [
                "gogs",
                "health",
                "git.example.test",
                "--json",
                "--min-free-bytes",
                "2048",
                "--min-free-inodes",
                "50",
            ]
        )

        self.assertEqual(args.gogs_command, "health")
        self.assertTrue(args.json)
        self.assertEqual(args.min_free_bytes, 2048)
        self.assertEqual(args.min_free_inodes, 50)

    def test_parser_accepts_repository_configuration(self):
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command")
        add_gogs_subparser(commands)

        args = parser.parse_args(
            [
                "gogs",
                "repo-configure",
                "/srv/project",
                "--github-url",
                "https://github.com/team/project.git",
                "--gogs-url",
                "https://git.example.test/team/project.git",
                "--track",
                "assets/**",
                "--dry-run",
            ]
        )

        self.assertEqual(args.gogs_command, "repo-configure")
        self.assertEqual(args.track, ["assets/**"])
        self.assertTrue(args.dry_run)


class TestRemoteGogsHealth(unittest.TestCase):
    def test_remote_probe_uses_noninteractive_sudo_and_parses_json(self):
        payload = _healthy_result()
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        with (
            patch("lib.gogs_cli.validate_host", return_value=True),
            patch("lib.gogs_cli.validate_username", return_value=True),
            patch("lib.gogs_cli._resolve_connection", return_value=("deploy", None)),
            patch("lib.gogs_cli.build_ssh_command", return_value=["ssh-command"]) as build,
            patch("lib.gogs_cli.subprocess.run", return_value=completed),
        ):
            result = inspect_remote_gogs("host", None, None, 100, 10)

        self.assertEqual(result, payload)
        self.assertTrue(build.call_args.kwargs["remote_command"].startswith("sudo -n python3 -c "))

    def test_remote_script_checks_git_access_timer_and_lfs_configuration(self):
        script = _remote_health_script(100, 10)

        compile(script, "<gogs-health>", "exec")
        self.assertIn('runuser", "-u", "git"', script)
        self.assertIn('auto-update-gogs.timer', script)
        self.assertIn('timer_scheduled', script)
        self.assertIn('remote_lfs_endpoint_configured', script)
        self.assertIn('update_check_stale', script)
        self.assertIn('client_max_body_size', script)
        self.assertIn('run("nginx", "-t")', script)
        self.assertIn('frontend_healthy', script)
        self.assertIn('"--cacert", cert_path', script)

    def test_negative_threshold_is_rejected_before_ssh(self):
        with patch("lib.gogs_cli.subprocess.run") as runner:
            with self.assertRaisesRegex(ValueError, "non-negative"):
                inspect_remote_gogs("host", "root", None, -1, 0)
        runner.assert_not_called()


class TestGogsHealthOutput(unittest.TestCase):
    def test_text_output_contains_operator_facts(self):
        output = _format_health(_healthy_result(), "git.example.test")

        self.assertIn("Gogs health for git.example.test: healthy", output)
        self.assertIn("/dev/vdb1 (ext4)", output)
        self.assertIn("Remote LFS endpoint: configured", output)
        self.assertIn("Nginx: ok", output)
        self.assertIn("Public web endpoint: ok", output)

    def test_unhealthy_json_returns_nonzero(self):
        value = _healthy_result()
        value["healthy"] = False
        args = argparse.Namespace(
            gogs_command="health",
            host="host",
            username=None,
            ssh_key=None,
            min_free_bytes=1,
            min_free_inodes=1,
            json=True,
        )
        output = io.StringIO()
        with (
            patch("lib.gogs_cli.inspect_remote_gogs", return_value=value),
            redirect_stdout(output),
        ):
            result = run_gogs_command(args)

        self.assertEqual(result, 1)
        self.assertFalse(json.loads(output.getvalue())["healthy"])


if __name__ == "__main__":
    unittest.main()
