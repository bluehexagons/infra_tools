"""Tests for local orchestration-host bootstrap helpers."""

from __future__ import annotations

import os
import pwd
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import orchestrator_bootstrap


class TestResolveBootstrapUser(unittest.TestCase):
    @patch.dict("lib.orchestrator_bootstrap.os.environ", {"SUDO_USER": "admin"}, clear=False)
    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=0)
    @patch("lib.orchestrator_bootstrap.validate_username", return_value=True)
    @patch("lib.orchestrator_bootstrap.pwd.getpwnam")
    def test_defaults_to_sudo_user_when_running_as_root(
        self,
        mock_getpwnam,
        _mock_validate_username,
        _mock_geteuid,
    ):
        mock_getpwnam.return_value = pwd.struct_passwd(("admin", "x", 1000, 1000, "", "/home/admin", "/bin/bash"))
        username, home_dir = orchestrator_bootstrap.resolve_bootstrap_user(None)
        self.assertEqual(username, "admin")
        self.assertEqual(home_dir, "/home/admin")


class TestInstallSystemPackages(unittest.TestCase):
    @patch("lib.orchestrator_bootstrap.subprocess.run")
    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=0)
    def test_installs_bash_completion_for_bash(self, _mock_geteuid, mock_run):
        mock_run.side_effect = [
            unittest.mock.MagicMock(returncode=0, stdout="", stderr=""),
            unittest.mock.MagicMock(returncode=0, stdout="", stderr=""),
        ]
        result = orchestrator_bootstrap.install_system_packages("bash")
        self.assertEqual(result, 0)
        install_args = mock_run.call_args_list[1].args[0]
        self.assertIn("bash-completion", install_args)


class TestRunOrchestratorBootstrap(unittest.TestCase):
    @patch("lib.orchestrator_bootstrap.install_launcher", return_value="/usr/local/bin/infra_tools")
    @patch("lib.orchestrator_bootstrap.resolve_bootstrap_user", return_value=("admin", "/home/admin"))
    @patch("lib.orchestrator_bootstrap.install_system_packages", return_value=0)
    @patch("lib.orchestrator_bootstrap.get_current_username", return_value="root")
    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=0)
    @patch("lib.orchestrator_bootstrap.subprocess.run")
    def test_runs_python_tools_as_target_user(
        self,
        mock_run,
        _mock_geteuid,
        _mock_current_username,
        _mock_install_packages,
        _mock_resolve_user,
        mock_install_launcher,
    ):
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)
        result = orchestrator_bootstrap.run_orchestrator_bootstrap(
            script_path="infra_tools.py",
            shell="bash",
            requested_user="admin",
        )
        self.assertEqual(result, 0)
        mock_install_launcher.assert_called_once()
        command = mock_run.call_args.args[0]
        self.assertEqual(command[:4], ["runuser", "-u", "admin", "--"])
        self.assertIn("python-tools", command)
        self.assertIn("--script-path", command)

    @patch("lib.orchestrator_bootstrap.resolve_bootstrap_user", return_value=("admin", "/home/admin"))
    @patch("lib.orchestrator_bootstrap.get_current_username", return_value="admin")
    @patch("lib.orchestrator_bootstrap.subprocess.run")
    def test_can_skip_system_packages_for_current_user(
        self,
        mock_run,
        _mock_current_username,
        _mock_resolve_user,
    ):
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)
        result = orchestrator_bootstrap.run_orchestrator_bootstrap(
            script_path="infra_tools.py",
            shell="zsh",
            requested_user="admin",
            skip_system_packages=True,
        )
        self.assertEqual(result, 0)
        command = mock_run.call_args.args[0]
        self.assertIn("python-tools", command)
        self.assertEqual(command[-4:-2], ["--shell", "zsh"])
        self.assertEqual(command[-2], "--script-path")


class TestInstallLauncher(unittest.TestCase):
    def test_install_launcher_writes_executable_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_script = os.path.join(tmp, "infra_tools.py")
            with open(project_script, "w", encoding="utf-8") as handle:
                handle.write("# fake script\n")
            target_dir = os.path.join(tmp, "bin")
            launcher = orchestrator_bootstrap.install_launcher(
                project_script, target_dir=target_dir
            )
            self.assertEqual(launcher, os.path.join(target_dir, "infra_tools"))
            self.assertTrue(os.access(launcher, os.X_OK))
            content = open(launcher, encoding="utf-8").read()
            self.assertIn("#!/usr/bin/env bash", content)
            self.assertIn(project_script, content)
            self.assertIn("exec python3", content)

    def test_install_launcher_rejects_missing_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                orchestrator_bootstrap.install_launcher(
                    os.path.join(tmp, "nope.py"), target_dir=tmp
                )


class TestInstallTmpfilesConf(unittest.TestCase):
    def test_build_content_includes_all_prefixes_and_dirs(self):
        from lib.maintenance_defaults import INFRA_TMP_DIRS, INFRA_TMP_PREFIXES
        content = orchestrator_bootstrap._build_tmpfiles_conf_content()
        for prefix in INFRA_TMP_PREFIXES:
            self.assertIn(prefix, content)
        for tmp_dir in INFRA_TMP_DIRS:
            self.assertIn(tmp_dir, content)
        self.assertIn("infra_tools", content)

    def test_build_content_uses_correct_age(self):
        from lib.maintenance_defaults import STALE_INFRA_TMP_MAX_AGE_DAYS
        content = orchestrator_bootstrap._build_tmpfiles_conf_content()
        self.assertIn(f"{STALE_INFRA_TMP_MAX_AGE_DAYS}d", content)

    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=0)
    def test_install_creates_conf_file(self, _mock_geteuid):
        with tempfile.TemporaryDirectory() as tmp:
            conf_path = os.path.join(tmp, "infra_tools.conf")
            orchestrator_bootstrap.install_tmpfiles_conf(conf_path=conf_path)
            self.assertTrue(os.path.isfile(conf_path))
            content = open(conf_path, encoding="utf-8").read()
            self.assertIn("infra_tools", content)
            mode = os.stat(conf_path).st_mode & 0o777
            self.assertEqual(mode, 0o644)

    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=1000)
    def test_install_raises_without_root(self, _mock_geteuid):
        with self.assertRaises(PermissionError):
            orchestrator_bootstrap.install_tmpfiles_conf()

    @patch("lib.orchestrator_bootstrap.install_tmpfiles_conf")
    @patch("lib.orchestrator_bootstrap.install_launcher", return_value="/usr/local/bin/infra_tools")
    @patch("lib.orchestrator_bootstrap.subprocess.run")
    @patch("lib.orchestrator_bootstrap.os.geteuid", return_value=0)
    def test_bootstrap_installs_tmpfiles_conf(
        self, _mock_geteuid, mock_run, _mock_launcher, mock_tmpfiles
    ):
        mock_run.side_effect = [
            unittest.mock.MagicMock(returncode=0, stdout="", stderr=""),
            unittest.mock.MagicMock(returncode=0, stdout="", stderr=""),
            unittest.mock.MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with patch("lib.orchestrator_bootstrap.resolve_bootstrap_user", return_value=("admin", "/home/admin")):
            with patch("lib.orchestrator_bootstrap.get_current_username", return_value="admin"):
                orchestrator_bootstrap.run_orchestrator_bootstrap("infra_tools.py", "bash", None)
        mock_tmpfiles.assert_called_once()


if __name__ == "__main__":
    unittest.main()
