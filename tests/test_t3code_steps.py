"""Tests for the T3 Code server setup path."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.t3code_steps import (
    _active_t3_binary,
    _configure_firewall,
    _configure_t3_https,
    _install_t3_service,
    _write_passthrough_wrapper,
    install_t3code_web,
)
from lib.config import SetupConfig
from lib.validation import validate_web_interface_settings


class T3CodeWebTest(unittest.TestCase):
    def _config(self, **overrides) -> SetupConfig:
        values = {
            "host": "target",
            "username": "agent",
            "system_type": "server_dev",
            "agent_tools": ["codex"],
            "web_interfaces": ["t3code"],
            "web_interface_sources": ["192.168.0.0/24"],
        }
        values.update(overrides)
        return SetupConfig(**values)

    @staticmethod
    def _write_upstream_runtime(home: str, version: str = "0.0.34") -> str:
        runtime = os.path.join(home, ".t3", "runtime")
        binary = os.path.join(
            runtime,
            "versions",
            version,
            "node_modules",
            "t3",
            "dist",
            "bin.mjs",
        )
        os.makedirs(os.path.dirname(binary), exist_ok=True)
        with open(binary, "w", encoding="utf-8") as file_obj:
            file_obj.write("#!/usr/bin/env node\n")
        os.chmod(binary, 0o755)
        with open(
            os.path.join(runtime, "service-state.json"),
            "w",
            encoding="utf-8",
        ) as file_obj:
            json.dump({"protocol": 2, "activeVersion": version}, file_obj)
        service = os.path.join(home, ".config", "systemd", "user", "t3code.service")
        os.makedirs(os.path.dirname(service), exist_ok=True)
        with open(service, "w", encoding="utf-8") as file_obj:
            file_obj.write("# upstream managed\n")
        return binary

    def test_source_promotes_default_bind_to_all_interfaces(self) -> None:
        config = self._config()
        self.assertEqual(config.web_interface_host, "0.0.0.0")
        validate_web_interface_settings(config)

    def test_https_gateway_is_optional_when_managed_utility_is_unavailable(self) -> None:
        with patch("common.t3code_steps.os.path.isfile", return_value=False):
            self.assertEqual(_configure_t3_https(self._config(), 3773, None), [])

    def test_non_loopback_bind_requires_private_source(self) -> None:
        config = self._config(web_interface_host="0.0.0.0", web_interface_sources=None)
        with self.assertRaisesRegex(
            ValueError,
            "requires --access-source or --web-interface-source",
        ):
            validate_web_interface_settings(config)

    def test_loopback_bind_rejects_redundant_source_allowlist(self) -> None:
        config = self._config(web_interface_host="127.0.0.1")
        with self.assertRaisesRegex(ValueError, "requires a non-loopback"):
            validate_web_interface_settings(config)

    def test_global_source_is_rejected(self) -> None:
        config = self._config(web_interface_sources=["8.8.8.0/24"])
        with self.assertRaisesRegex(ValueError, "private or otherwise non-global"):
            validate_web_interface_settings(config)

    def test_firewall_reconciles_stale_managed_source_rules(self) -> None:
        config = self._config(
            web_interface_host="0.0.0.0",
            web_interface_sources=["10.0.0.0/24"],
        )
        state = {"allow_seen": False}

        def run_command(command: str, **_kwargs):
            if command == "ufw status numbered":
                rules = (
                    "[ 1] 3773/tcp ALLOW IN 192.168.0.0/24 "
                    "# infra_tools T3 Code 3773/tcp source 192.168.0.0/24\n"
                )
                if state["allow_seen"]:
                    rules += (
                        "[ 2] 3773/tcp ALLOW IN 10.0.0.0/24 "
                        "# infra_tools T3 Code 3773/tcp source 10.0.0.0/24\n"
                    )
                return SimpleNamespace(returncode=0, stdout=rules)
            if command.startswith("ufw allow from"):
                state["allow_seen"] = True
            return SimpleNamespace(returncode=0, stdout="")

        with patch("common.t3code_steps.run", side_effect=run_command) as mock_run:
            _configure_firewall(config, 3773, "0.0.0.0")

        self.assertTrue(
            any("ufw --force delete 1" in call.args[0] for call in mock_run.call_args_list)
        )

    def test_firewall_rejects_unmanaged_port_rule(self) -> None:
        config = self._config(web_interface_host="0.0.0.0")

        def run_command(command: str, **_kwargs):
            if command == "ufw status numbered":
                return SimpleNamespace(
                    returncode=0,
                    stdout="[ 1] 3773/tcp ALLOW IN Anywhere\n",
                )
            return SimpleNamespace(returncode=0, stdout="")

        with patch("common.t3code_steps.run", side_effect=run_command):
            with self.assertRaisesRegex(RuntimeError, "Unmanaged UFW allow rules"):
                _configure_firewall(config, 3773, "0.0.0.0")

    def test_active_binary_requires_upstream_protocol_and_exact_version(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            binary = self._write_upstream_runtime(home)
            self.assertEqual(_active_t3_binary(home), binary)
            state_file = os.path.join(home, ".t3", "runtime", "service-state.json")
            with open(state_file, "w", encoding="utf-8") as file_obj:
                json.dump(
                    {"protocolVersion": 2, "activeVersion": "0.0.34"},
                    file_obj,
                )
            self.assertIsNone(_active_t3_binary(home))

            build_binary = self._write_upstream_runtime(
                home,
                "1.2.3-nightly.1+build.5",
            )
            self.assertEqual(_active_t3_binary(home), build_binary)

            self._write_upstream_runtime(home, "01.2.3")
            self.assertIsNone(_active_t3_binary(home))

    def test_service_install_uses_upstream_npx_update_and_managed_drop_in(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            workspace = os.path.join(home, "repos")
            os.makedirs(workspace)
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            commands: list[str] = []

            def run_as_user(_username, _home, command, **_kwargs):
                commands.append(command)
                self._write_upstream_runtime(home)
                return completed

            with (
                patch("common.t3code_steps.install_package", return_value=True),
                patch("common.t3code_steps._ensure_user_manager"),
                patch(
                    "common.t3code_steps._node_bin_directory",
                    return_value="/usr/bin",
                ),
                patch("common.t3code_steps._run_as_login_user", side_effect=run_as_user),
                patch("common.t3code_steps._user_systemctl", return_value=completed),
                patch("common.t3code_steps.os.chown"),
                patch(
                    "common.t3code_steps.LEGACY_T3_SERVICE_FILE",
                    os.path.join(home, "legacy.service"),
                ),
            ):
                binary, changed = _install_t3_service(
                    home,
                    "agent",
                    os.getuid(),
                    os.getgid(),
                    workspace,
                    "0.0.0.0",
                    3773,
                )

            self.assertTrue(changed)
            self.assertEqual(binary, _active_t3_binary(home))
            self.assertTrue(
                any("npx --yes t3@latest service update" in command for command in commands)
            )
            drop_in = os.path.join(
                home,
                ".config",
                "systemd",
                "user",
                "t3code.service.d",
                "infra-tools.conf",
            )
            with open(drop_in, encoding="utf-8") as file_obj:
                content = file_obj.read()
            self.assertIn(f"WorkingDirectory={workspace}", content)
            self.assertIn("Environment=T3CODE_HOST=0.0.0.0", content)
            self.assertIn("Environment=T3CODE_PORT=3773", content)

    def test_healthy_service_is_not_silently_updated(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            workspace = os.path.join(home, "repos")
            os.makedirs(workspace)
            self._write_upstream_runtime(home)
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with (
                patch("common.t3code_steps.install_package", return_value=True),
                patch("common.t3code_steps._ensure_user_manager"),
                patch("common.t3code_steps._node_bin_directory", return_value="/usr/bin"),
                patch("common.t3code_steps._run_as_login_user") as run_as_user,
                patch("common.t3code_steps._user_systemctl", return_value=completed),
                patch("common.t3code_steps.os.chown"),
                patch(
                    "common.t3code_steps.LEGACY_T3_SERVICE_FILE",
                    os.path.join(home, "legacy.service"),
                ),
            ):
                _install_t3_service(
                    home,
                    "agent",
                    os.getuid(),
                    os.getgid(),
                    workspace,
                    "127.0.0.1",
                    3773,
                )
            run_as_user.assert_not_called()

    def test_legacy_root_service_is_retired_after_user_service_starts(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            workspace = os.path.join(home, "repos")
            os.makedirs(workspace)
            self._write_upstream_runtime(home)
            legacy_service = os.path.join(home, "infra-tools-t3code.service")
            with open(legacy_service, "w", encoding="utf-8") as file_obj:
                file_obj.write("# legacy infra-tools unit\n")
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with (
                patch("common.t3code_steps.install_package", return_value=True),
                patch("common.t3code_steps._ensure_user_manager"),
                patch("common.t3code_steps._node_bin_directory", return_value="/usr/bin"),
                patch("common.t3code_steps._run_as_login_user") as run_as_user,
                patch("common.t3code_steps._user_systemctl", return_value=completed),
                patch("common.t3code_steps.run", return_value=completed) as run_command,
                patch("common.t3code_steps.os.chown"),
                patch(
                    "common.t3code_steps.LEGACY_T3_SERVICE_FILE",
                    legacy_service,
                ),
            ):
                _install_t3_service(
                    home,
                    "agent",
                    os.getuid(),
                    os.getgid(),
                    workspace,
                    "127.0.0.1",
                    3773,
                )

            run_as_user.assert_not_called()
            self.assertFalse(os.path.exists(legacy_service))
            commands = [call.args[0] for call in run_command.call_args_list]
            self.assertIn(
                ["systemctl", "stop", "infra-tools-t3code.service"],
                commands,
            )
            self.assertIn(
                ["systemctl", "disable", "infra-tools-t3code.service"],
                commands,
            )

    def test_stable_wrapper_follows_service_selected_version(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, ".local", "bin")
            os.makedirs(bin_dir)
            wrapper = os.path.join(bin_dir, "t3")
            self.assertTrue(_write_passthrough_wrapper(wrapper, home))
            with open(wrapper, encoding="utf-8") as file_obj:
                content = file_obj.read()
            self.assertIn("service-state.json", content)
            self.assertIn('value.get("protocol") == 2', content)
            self.assertIn('NVM_DIR="$HOME/.nvm"', content)
            self.assertIn("versions", content)
            self.assertIn('exec "$binary" "$@"', content)
            self.assertNotIn("npx", content)

    def test_web_step_is_server_only_and_uses_upstream_service(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            account = SimpleNamespace(
                pw_dir=home,
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
            )
            workspace = os.path.join(home, "repos")
            os.makedirs(workspace)
            binary = self._write_upstream_runtime(home)
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            admin_pair_script = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "common",
                "service_tools",
                "t3code_admin_pair.py",
            )
            with (
                patch("common.t3code_steps.pwd.getpwnam", return_value=account),
                patch("common.t3code_steps.os.chown"),
                patch("common.t3code_steps._configure_firewall"),
                patch(
                    "common.t3code_steps._install_t3_service",
                    return_value=(binary, True),
                ),
                patch("common.t3code_steps._user_systemctl", return_value=completed),
                patch("common.t3code_steps._ensure_t3_agent_skill", return_value=False),
                patch("common.t3code_steps._remove_connect_restart_units"),
                patch("common.t3code_steps._remove_device_pairing"),
                patch("common.t3code_steps._remove_t3_https"),
                patch("common.t3code_steps._configure_t3_https", return_value=[]),
                patch("common.t3code_steps.T3_ADMIN_PAIR_SCRIPT", admin_pair_script),
            ):
                install_t3code_web(
                    self._config(
                        web_interface_sources=None,
                        web_interface_host="127.0.0.1",
                        agent_workspace=workspace,
                    )
                )

            wrapper = os.path.join(
                home,
                ".local",
                "bin",
                "infra-tools-t3code-pairing-provider",
            )
            pair_wrapper = os.path.join(home, ".local", "bin", "t3code-pair")
            self.assertTrue(os.path.isfile(wrapper))
            self.assertTrue(os.path.isfile(pair_wrapper))
            self.assertFalse(
                os.path.exists(os.path.join(home, ".local", "share", "t3code"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(home, ".local", "share", "applications"))
            )


if __name__ == "__main__":
    unittest.main()
