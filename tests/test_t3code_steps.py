"""Tests for the explicit T3 Code web-interface setup path."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.t3code_steps import (
    _configure_firewall,
    _configure_t3_https,
    _remove_legacy_t3_shim,
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

    def test_source_promotes_default_bind_to_all_interfaces(self) -> None:
        config = self._config()
        self.assertEqual(config.web_interface_host, "0.0.0.0")
        validate_web_interface_settings(config)

    def test_https_gateway_is_optional_when_managed_utility_is_unavailable(self) -> None:
        config = self._config()
        with patch(
            "common.t3code_steps.os.path.isfile",
            return_value=False,
        ):
            self.assertEqual(_configure_t3_https(config, 3773, None), [])

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

        self.assertTrue(any("ufw --force delete 1" in call.args[0] for call in mock_run.call_args_list))

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

    def test_legacy_shim_is_removed_but_unmanaged_launcher_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            shim_dir = os.path.join(
                temporary, ".local", "share", "infra-tools", "t3code", "shims"
            )
            os.makedirs(shim_dir)
            shim = os.path.join(shim_dir, "gh")
            with open(shim, "w", encoding="utf-8") as file_obj:
                file_obj.write("t3code_gh_shim.py\n")
            self.assertTrue(_remove_legacy_t3_shim(temporary))
            self.assertFalse(os.path.exists(shim))

            os.makedirs(shim_dir)
            with open(shim, "w", encoding="utf-8") as file_obj:
                file_obj.write("#!/bin/sh\nexec /usr/bin/gh \"$@\"\n")
            self.assertFalse(_remove_legacy_t3_shim(temporary))
            self.assertTrue(os.path.isfile(shim))

    def test_web_step_writes_service_and_pairing_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            account = SimpleNamespace(pw_dir=temporary, pw_uid=os.getuid(), pw_gid=os.getgid())
            config = self._config(
                agent_tools=["gh", "codex"],
                agent_workspace=os.path.join(temporary, "repos"),
            )
            service_path = os.path.join(temporary, "t3code.service")
            pairing_config_dir = os.path.join(temporary, "device-pairing")
            admin_pair_script = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "common",
                "service_tools",
                "t3code_admin_pair.py",
            )
            def run_command(command: str, **_kwargs):
                if command == "ufw status numbered":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            "[ 1] 3773/tcp ALLOW IN 192.168.0.0/24 "
                            "# infra_tools T3 Code 3773/tcp source 192.168.0.0/24\n"
                        ),
                    )
                return SimpleNamespace(returncode=0, stdout="")

            with (
                patch("common.t3code_steps.pwd.getpwnam", return_value=account),
                patch("common.t3code_steps.os.chown"),
                patch(
                    "common.t3code_steps.run",
                    side_effect=run_command,
                ),
                patch("common.t3code_steps.install_package", return_value=True),
                patch(
                    "common.t3code_steps._run_as_login_user",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ),
                patch(
                    "common.t3code_steps._configure_t3_https",
                    return_value=[("https://target:8444/", 8444)],
                ),
                patch("common.t3code_steps.T3_SERVICE_FILE", service_path),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_SERVICE_FILE",
                    os.path.join(temporary, "infra-tools-device-pairing.service"),
                ),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_CONFIG_DIR",
                    pairing_config_dir,
                ),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_AUTH_FILE",
                    os.path.join(pairing_config_dir, "htpasswd"),
                ),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_PROVIDERS_FILE",
                    os.path.join(pairing_config_dir, "providers.json"),
                ),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_NGINX_SITE",
                    os.path.join(
                        temporary,
                        "nginx",
                        "sites-available",
                        "device-pairing",
                    ),
                ),
                patch(
                    "common.t3code_steps.DEVICE_PAIRING_NGINX_LINK",
                    os.path.join(
                        temporary,
                        "nginx",
                        "sites-enabled",
                        "device-pairing",
                    ),
                ),
                patch(
                    "common.t3code_steps.T3_ADMIN_PAIR_SCRIPT",
                    admin_pair_script,
                ),
                patch("common.t3code_steps.remove_nginx_auth_failure_ban"),
            ):
                install_t3code_web(config)

            wrapper = os.path.join(temporary, ".local", "bin", "infra-tools-t3code-web")
            pair_wrapper = os.path.join(temporary, ".local", "bin", "t3code-pair")
            cli_wrapper = os.path.join(
                temporary,
                ".local",
                "bin",
                "infra-tools-t3code-pairing-provider",
            )
            self.assertTrue(os.path.exists(wrapper))
            self.assertTrue(os.path.exists(pair_wrapper))
            self.assertTrue(os.path.exists(cli_wrapper))
            with open(wrapper, encoding="utf-8") as file_obj:
                content = file_obj.read()
            self.assertIn("serve --host 0.0.0.0 --port 3773 --no-browser", content)
            self.assertIn(
                f"exec {os.path.join(temporary, '.local', 'share', 'infra-tools', 't3code', 'node_modules', '.bin', 't3')}",
                content,
            )
            self.assertIn(f"cd {os.path.join(temporary, 'repos')}", content)
            self.assertNotIn("npx", content)
            self.assertIn(
                "$HOME/.local/share/infra-tools/t3code/node_modules/.bin:",
                content,
            )
            self.assertNotIn("t3code/shims", content)
            self.assertIn(
                "$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                content,
            )
            self.assertIn('export GH_CONFIG_DIR="$HOME/.config/gh"', content)
            with open(cli_wrapper, encoding="utf-8") as file_obj:
                cli_content = file_obj.read()
            self.assertIn(
                "$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                cli_content,
            )
            self.assertIn(
                'export GH_CONFIG_DIR="$HOME/.config/gh"',
                cli_content,
            )
            with open(pair_wrapper, encoding="utf-8") as file_obj:
                pairing_content = file_obj.read()
            self.assertIn("t3code_admin_pair.py", pairing_content)
            self.assertIn("--server-url http://127.0.0.1:3773", pairing_content)
            self.assertIn("--base-url https://target:8444/", pairing_content)
            with open(os.path.join(temporary, ".bashrc"), encoding="utf-8") as file_obj:
                bashrc = file_obj.read()
            self.assertIn("infra-tools T3 Code runtime", bashrc)
            skill = os.path.join(
                temporary,
                ".agents",
                "skills",
                "infra-tools-t3code",
                "SKILL.md",
            )
            self.assertTrue(os.path.isfile(skill))
            with open(skill, encoding="utf-8") as file_obj:
                self.assertIn("managed-by: infra_tools", file_obj.read())
            with open(service_path, encoding="utf-8") as file_obj:
                service = file_obj.read()
            self.assertIn("User=agent", service)
            self.assertIn(f"RequiresMountsFor={temporary}", service)
            self.assertIn(f"RequiresMountsFor={os.path.join(temporary, 'repos')}", service)
            self.assertIn("StandardOutput=null", service)
            self.assertIn("infra-tools-t3code-web", service)


if __name__ == "__main__":
    unittest.main()
