"""Behavioral tests for shared desktop control without host mutations."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop import session_runtime as runtime
from desktop.session_steps import assert_desktop_idle, install_session_runtime, prepare_shared_desktop
from lib.config import SetupConfig
from lib.arg_parser import create_setup_argument_parser
from lib.desktop_cli import add_desktop_subparser, run_desktop_command


class DesktopControlTests(unittest.TestCase):
    def setUp(self):
        ready = patch.object(runtime, "window_manager_ready", return_value=True)
        ready.start()
        self.addCleanup(ready.stop)
        self.geometry = patch.object(runtime, "geometry", return_value=[1280, 720])
        self.geometry.start()
        self.addCleanup(self.geometry.stop)
        self.environment = patch.dict("os.environ", {"DISPLAY": ":10"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.process = Mock(pid=54321)
        self.process.poll.return_value = None
        self.session = runtime.DesktopSession({"desktop": "xfce", "username": "agent"}, self.process)

    def acquire(self):
        return self.session.handle({"action": "acquire", "generation": self.session.generation})

    def test_human_takeover_revokes_lease_but_keeps_observation(self):
        lease = self.acquire()
        self.session.handle({"action": "pause"})
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.session.handle({"action": "exec", **lease, "argv": ["editor"]})
        self.assertEqual(self.session.handle({"action": "status"})["state"], "running")
        self.session.handle({"action": "resume"})
        with self.assertRaisesRegex(ValueError, "lease"):
            self.session.handle({"action": "exec", **lease, "argv": ["editor"]})

    def test_second_agent_cannot_interleave_control(self):
        lease = self.acquire()
        with self.assertRaisesRegex(RuntimeError, "leased"):
            self.acquire()
        self.session.handle({"action": "release", **lease})
        self.assertNotEqual(self.acquire()["lease"], lease["lease"])

    @patch.object(runtime, "run_tool")
    def test_stale_session_and_geometry_never_send_input(self, tool):
        lease = self.acquire()
        payload = {"action": "input", **lease, "geometry": [800, 600], "kind": "click", "x": 20, "y": 30}
        with self.assertRaisesRegex(ValueError, "geometry changed"):
            self.session.handle(payload)
        payload["generation"] = "old-session"
        with self.assertRaisesRegex(ValueError, "session changed"):
            self.session.handle(payload)
        tool.assert_not_called()

    @patch.object(runtime.subprocess, "Popen")
    def test_application_launch_uses_argv_and_desktop_process_group(self, popen):
        popen.return_value.pid = 42
        result = self.session.handle({"action": "exec", **self.acquire(), "argv": ["editor", "$(not-a-shell)"]})
        self.assertEqual(result["pid"], 42)
        self.assertEqual(popen.call_args.args[0], ["editor", "$(not-a-shell)"])
        self.assertEqual(popen.call_args.kwargs["process_group"], self.process.pid)

    def test_expired_lease_is_rejected(self):
        lease = self.acquire()
        self.session.lease_until = 0
        with self.assertRaisesRegex(ValueError, "lease"):
            self.session.handle({"action": "exec", **lease, "argv": ["editor"]})

    @patch.object(runtime, "window_manager_ready", return_value=False)
    def test_starting_desktop_is_not_reported_ready(self, ready):
        self.assertEqual(self.session.snapshot_status()["state"], "starting")

    @patch.object(runtime, "run_tool")
    def test_invalid_click_does_not_even_move_pointer(self, tool):
        with self.assertRaisesRegex(ValueError, "Button"):
            self.session.handle({"action": "input", **self.acquire(), "geometry": [1280, 720],
                                 "kind": "click", "x": 10, "y": 10, "button": 9})
        tool.assert_not_called()

    @patch.object(runtime, "run_tool")
    def test_screenshot_reports_captured_pixels_and_private_permissions(self, tool):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            tool.side_effect = lambda _: path.write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1280, 720))
            result = self.session.handle({"action": "screenshot", "generation": self.session.generation,
                                          "output": str(path)})
            self.assertEqual(result["geometry"], [1280, 720])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @patch.object(runtime, "run_tool")
    def test_screenshot_rejects_scrot_filename_expansion(self, tool):
        with self.assertRaisesRegex(ValueError, "format characters"):
            self.session.handle({"action": "screenshot", "generation": self.session.generation,
                                 "output": "/tmp/$w.png"})
        tool.assert_not_called()

    @patch.object(runtime, "run_tool")
    def test_screenshot_refuses_overwrite_and_cleans_failed_capture(self, tool):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            path.write_text("existing")
            payload = {"action": "screenshot", "generation": self.session.generation, "output": str(path)}
            with self.assertRaises(FileExistsError):
                self.session.handle(payload)
            self.assertEqual(path.read_text(), "existing")
            path.unlink()
            tool.side_effect = RuntimeError("capture failed")
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                self.session.handle(payload)
            self.assertFalse(path.exists())

    @patch.object(runtime.subprocess, "Popen")
    def test_logout_requests_desktop_logout_without_killing_other_services(self, popen):
        result = self.session.handle({"action": "logout", **self.acquire()})
        self.assertTrue(result["logout_requested"])
        popen.assert_called_once_with(["xfce4-session-logout", "--logout"], process_group=self.process.pid)
        self.process.terminate.assert_not_called()


class DesktopStartTests(unittest.TestCase):
    @patch.object(runtime, "configuration")
    @patch.object(runtime, "session_lock")
    @patch.object(runtime, "status", side_effect=[{"state": "starting"}, {"state": "running"}])
    @patch.object(runtime.subprocess, "run")
    def test_join_human_start_without_a_second_start_request(self, run, status, lock, config):
        self.assertEqual(runtime.start()["state"], "running")
        run.assert_not_called()

    @patch.object(runtime, "configuration")
    @patch.object(runtime, "session_lock")
    @patch.object(runtime, "status", return_value={"state": "running", "generation": "same"})
    @patch.object(runtime.subprocess, "run")
    def test_repeated_start_reuses_running_session(self, run, status, lock, config):
        self.assertEqual(runtime.start()["generation"], "same")
        run.assert_not_called()

    @patch.object(runtime, "configuration")
    @patch.object(runtime, "session_lock")
    @patch.object(runtime, "status", side_effect=[{"state": "stopped"}, {"state": "running"}])
    @patch.object(runtime.subprocess, "run", return_value=Mock(returncode=0))
    def test_start_authenticates_as_current_uid_without_password(self, run, status, lock, config):
        self.assertEqual(runtime.start()["state"], "running")
        self.assertEqual(run.call_args.args[0], ["xrdp-sesrun", "-t", "Xorg", "-g", "1280x720", "-b", "32"])


class DesktopMigrationTests(unittest.TestCase):
    @patch("common.agent_steps.install_managed_agent_skills")
    @patch("common.agent_steps.install_agent_cli_launcher")
    @patch("desktop.session_steps.pwd.getpwnam", return_value=Mock(pw_uid=1000))
    @patch("desktop.session_steps.assert_desktop_idle")
    @patch("desktop.session_steps.is_dry_run", return_value=False)
    @patch("desktop.session_steps.run")
    def test_install_is_repeatable_and_backs_up_prior_owner_declaration(self, run, dry, idle, account, cli, skills):
        with tempfile.TemporaryDirectory() as directory:
            declaration = Path(directory) / "desktop.json"
            wrapper = Path(directory) / "startwm.sh"
            config = SetupConfig(host="vm", username="agent", system_type="agent_vm", agent_tools=["codex"])
            with patch("desktop.session_steps.CONFIG_PATH", declaration), patch("desktop.session_steps.STARTWM", str(wrapper)):
                install_session_runtime(config)
                first = declaration.read_text()
                config.desktop = "i3"
                install_session_runtime(config)
            self.assertEqual(json.loads(declaration.read_text())["desktop"], "i3")
            self.assertEqual(declaration.with_suffix(".json.bak").read_text(), first)
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
            self.assertIn("dbus-run-session", wrapper.read_text())
            self.assertIn(["gpasswd", "-M", "agent", "infra-desktop"], [call.args[0] for call in run.call_args_list])
            self.assertEqual(skills.call_args.args, ("agent", ["codex"], ("infra-tools-desktop",)))

    @patch("desktop.session_steps.assert_desktop_idle")
    @patch("desktop.session_steps.is_dry_run", return_value=False)
    @patch("desktop.session_steps.run")
    def test_already_masked_console_is_safe_to_reconcile(self, run, dry, idle):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "display-manager.service"
            alias.symlink_to("/dev/null")
            with patch("desktop.session_steps.DISPLAY_MANAGER_ALIAS", alias):
                prepare_shared_desktop(SetupConfig(host="vm", username="agent", system_type="agent_vm"))
            self.assertEqual(alias.readlink(), Path("/dev/null"))
            self.assertFalse(alias.with_suffix(".service.infra-tools-backup").exists())
            self.assertEqual(run.call_args.args[0][:3], ["systemctl", "mask", "--now"])

    @patch("desktop.session_steps.run")
    def test_hardened_user_fails_before_service_changes(self, run):
        config = SetupConfig(host="vm", username="agent", system_type="agent_workstation", harden_user=True)
        with self.assertRaisesRegex(ValueError, "harden-user"):
            assert_desktop_idle(config)
        run.assert_not_called()

    @patch("desktop.session_steps.is_dry_run", return_value=False)
    @patch("desktop.session_steps.run")
    def test_active_wayland_desktop_blocks_migration_without_stopping_it(self, run, dry):
        run.side_effect = [Mock(stdout="1 1000 agent seat0\n"), Mock(stdout="Type=wayland\nClass=user\n")]
        config = SetupConfig(host="vm", username="agent", system_type="agent_workstation")
        with self.assertRaisesRegex(RuntimeError, "log out"):
            assert_desktop_idle(config)
        self.assertEqual(run.call_count, 2)

    @patch("desktop.session_steps.is_dry_run", return_value=False)
    @patch("desktop.session_steps.run")
    def test_unregistered_xrdp_session_also_blocks_migration(self, run, dry):
        run.side_effect = [Mock(stdout=""), Mock(returncode=0)]
        config = SetupConfig(host="vm", username="agent", system_type="agent_workstation")
        with self.assertRaisesRegex(RuntimeError, "XRDP sessions"):
            assert_desktop_idle(config)

    @patch("desktop.session_steps.run")
    def test_container_capability_failure_precedes_system_calls(self, run):
        config = SetupConfig(host="vm", username="agent", system_type="agent_workstation", machine_type="oci")
        with self.assertRaisesRegex(ValueError, "systemd"):
            assert_desktop_idle(config)
        run.assert_not_called()


class DesktopCliTests(unittest.TestCase):
    def test_remote_parser_does_not_turn_headless_forwarding_into_desktop(self):
        parser = create_setup_argument_parser("Remote", for_remote=True)
        args = parser.parse_args(["--system-type", "agent_vm", "--username", "agent"])
        args.host = "localhost"
        config = SetupConfig.from_args(args, "agent_vm")
        self.assertFalse(config.include_desktop)
        args = parser.parse_args(["--system-type", "agent_vm", "--username", "agent", "--desktop", "xfce"])
        args.host = "localhost"
        self.assertTrue(SetupConfig.from_args(args, "agent_vm").include_desktop)

    @patch.object(runtime, "status", return_value={"state": "stopped"})
    @patch.object(runtime, "start")
    def test_screenshot_does_not_implicitly_start_desktop(self, start, status):
        parser = argparse.ArgumentParser()
        add_desktop_subparser(parser.add_subparsers())
        args = parser.parse_args(["desktop", "screenshot", "--output", "/tmp/screen.png"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_desktop_command(args), 1)
        start.assert_not_called()


class DesktopPrivateRuntimeTests(unittest.TestCase):
    def test_runtime_directory_rejects_nonprivate_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            parent.chmod(0o755)
            with patch.object(runtime, "Path", return_value=parent):
                with self.assertRaisesRegex(RuntimeError, "private logind"):
                    runtime.runtime_directory()
            self.assertFalse((parent / "infra-tools-desktop").exists())

    def test_runtime_directory_is_private_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with patch.object(runtime, "Path", return_value=parent):
                first = runtime.runtime_directory()
                self.assertEqual(runtime.runtime_directory(), first)
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)

    def test_runtime_directory_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / "infra-tools-desktop").symlink_to(parent, target_is_directory=True)
            with patch.object(runtime, "Path", return_value=parent):
                with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                    runtime.runtime_directory()
