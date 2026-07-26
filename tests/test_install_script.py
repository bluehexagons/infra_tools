"""Integration tests for the curl/wget shell installer."""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SCRIPT = os.path.join(PROJECT_ROOT, "install.sh")


class TestInstallScript(unittest.TestCase):
    def _create_fixture(
        self,
        directory: str,
    ) -> tuple[str, str, dict[str, str]]:
        fake_home = os.path.join(directory, "home")
        source_root = os.path.join(directory, "archive", "infra_tools-test")
        fake_bin = os.path.join(directory, "bin")
        log_path = os.path.join(directory, "calls.jsonl")
        os.makedirs(fake_home)
        os.makedirs(source_root)
        os.makedirs(fake_bin)

        fake_cli = os.path.join(source_root, "infra_tools.py")
        with open(fake_cli, "w", encoding="utf-8") as file_obj:
            file_obj.write(textwrap.dedent(
                """\
                from __future__ import annotations
                import json
                import os
                import sys

                with open(os.environ["INFRA_TOOLS_TEST_LOG"], "a", encoding="utf-8") as log:
                    log.write(json.dumps(sys.argv[1:]) + "\\n")
                if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
                    if os.environ.get("INFRA_TOOLS_TEST_BOOTSTRAP_FAIL") == "1":
                        raise SystemExit(7)
                    launcher_dir = os.path.join(os.environ["HOME"], ".local", "bin")
                    os.makedirs(launcher_dir, exist_ok=True)
                    launcher = os.path.join(launcher_dir, "infra_tools")
                    with open(launcher, "w", encoding="utf-8") as output:
                        output.write("#!/bin/sh\\nexit 0\\n")
                    os.chmod(launcher, 0o755)
                """
            ))

        getent_path = os.path.join(fake_bin, "getent")
        with open(getent_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(
                "#!/bin/sh\n"
                f'printf "%s:x:%s:%s::%s:/bin/bash\\n" "$2" "$(id -u)" "$(id -g)" {fake_home!r}\n'
            )
        os.chmod(getent_path, 0o755)

        archive_path = os.path.join(directory, "fixture.tar.gz")
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(source_root, arcname="infra_tools-test")

        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join((fake_bin, environment.get("PATH", "")))
        environment["INFRA_TOOLS_ARCHIVE_FILE"] = archive_path
        environment["INFRA_TOOLS_TEST_LOG"] = log_path
        return fake_home, log_path, environment

    def test_installs_and_forwards_optional_setup_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_home, log_path, environment = self._create_fixture(directory)
            install_dir = os.path.join(directory, "installed")
            result = subprocess.run(
                [
                    "sh",
                    INSTALL_SCRIPT,
                    "--install-dir",
                    install_dir,
                    "--shell",
                    "bash",
                    "--setup",
                    "server_dev",
                    "10.0.0.50",
                    "agent",
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.isfile(os.path.join(install_dir, "infra_tools.py")))
            self.assertTrue(os.access(
                os.path.join(fake_home, ".local", "bin", "infra_tools"),
                os.X_OK,
            ))
            with open(log_path, encoding="utf-8") as file_obj:
                calls = [json.loads(line) for line in file_obj]
            self.assertEqual(calls[0][0], "bootstrap")
            self.assertEqual(
                calls[1],
                ["setup", "server_dev", "10.0.0.50", "agent", "--dry-run"],
            )

    def test_update_keeps_previous_source_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            _home, _log_path, environment = self._create_fixture(directory)
            install_dir = os.path.join(directory, "installed")
            os.makedirs(install_dir)
            with open(os.path.join(install_dir, "old-version"), "w", encoding="utf-8") as file_obj:
                file_obj.write("old")
            old_state = os.path.join(install_dir, "state")
            os.makedirs(old_state)
            with open(os.path.join(old_state, "setup.json"), "w", encoding="utf-8") as file_obj:
                file_obj.write("{}")

            result = subprocess.run(
                ["sh", INSTALL_SCRIPT, "--install-dir", install_dir],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            backups = glob.glob(f"{install_dir}.backup.*")
            self.assertEqual(len(backups), 1)
            self.assertTrue(os.path.isfile(os.path.join(backups[0], "old-version")))
            self.assertTrue(os.path.isfile(
                os.path.join(install_dir, "state", "setup.json")
            ))
            self.assertEqual(os.stat(backups[0]).st_mode & 0o777, 0o700)

    def test_bootstrap_failure_restores_previous_source(self):
        with tempfile.TemporaryDirectory() as directory:
            _home, _log_path, environment = self._create_fixture(directory)
            environment["INFRA_TOOLS_TEST_BOOTSTRAP_FAIL"] = "1"
            install_dir = os.path.join(directory, "installed")
            os.makedirs(install_dir)
            old_marker = os.path.join(install_dir, "old-version")
            with open(old_marker, "w", encoding="utf-8") as file_obj:
                file_obj.write("old")

            result = subprocess.run(
                ["sh", INSTALL_SCRIPT, "--install-dir", install_dir],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(os.path.isfile(old_marker))
            self.assertIn("previous install restored", result.stderr)

    def test_shell_syntax_and_help(self):
        syntax = subprocess.run(
            ["sh", "-n", INSTALL_SCRIPT],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        help_result = subprocess.run(
            ["sh", INSTALL_SCRIPT, "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--setup", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
