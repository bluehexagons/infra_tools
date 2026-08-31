"""Tests for the optional authenticated infra-tools control panel."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from common.control_panel_steps import (
    _configure_service,
    _install_auth_file,
    _write_nginx_site,
    build_control_panel_manifest,
    control_panel_url,
    remove_control_panel,
    render_control_panel_nginx,
)
from common.service_tools.control_panel_service import (
    ControlPanelState,
    _safe_url,
    render_page,
)
from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.display import print_service_access_summary
from lib.setup_common import prepare_control_panel_payload
from plugins.server import build_server_steps


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "agent-vm",
        "username": "agent",
        "system_type": "server_dev",
        "control_panel_port": 80,
    }
    values.update(overrides)
    return SetupConfig(**values)


class ControlPanelConfigTest(unittest.TestCase):
    def test_cli_defaults_to_http_or_https_standard_port(self) -> None:
        parser = create_setup_argument_parser("test")

        http = SetupConfig.from_args(
            parser.parse_args(["agent-vm", "agent", "--control-panel"]),
            "server_dev",
        )
        https = SetupConfig.from_args(
            parser.parse_args(
                ["agent-vm", "agent", "--control-panel", "--ssl"]
            ),
            "server_dev",
        )

        self.assertEqual(http.control_panel_port, 80)
        self.assertEqual(https.control_panel_port, 443)
        self.assertEqual(control_panel_url(http), "http://agent-vm/")
        self.assertEqual(control_panel_url(https), "https://agent-vm/")

    def test_cli_accepts_custom_port_and_keeps_password_transient(self) -> None:
        parser = create_setup_argument_parser("test")
        config = SetupConfig.from_args(
            parser.parse_args(
                [
                    "agent-vm",
                    "agent",
                    "--control-panel",
                    "9443",
                    "--control-panel-password",
                    "panel-secret",
                ]
            ),
            "server_dev",
        )

        self.assertEqual(config.control_panel_port, 9443)
        self.assertEqual(config.control_panel_auth_password, "panel-secret")
        self.assertNotIn("panel-secret", " ".join(config.to_remote_args()))
        self.assertNotIn("panel-secret", " ".join(config.to_setup_command()))
        self.assertNotIn("panel-secret", str(config.to_dict()))

    def test_explicit_zero_port_is_rejected(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            ["agent-vm", "agent", "--control-panel", "0"]
        )

        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            SetupConfig.from_args(args, "server_dev")

    def test_remote_payload_flag_is_serialized_without_secret(self) -> None:
        config = _config(control_panel_payload=True)
        remote = " ".join(config.to_remote_args())

        self.assertIn("--control-panel 80", remote)
        self.assertIn("--control-panel-payload", remote)
        self.assertNotIn("control_panel_payload", config.to_dict())

    def test_rejects_reserved_and_conflicting_ports(self) -> None:
        with self.assertRaisesRegex(ValueError, "8443 is reserved"):
            _config(control_panel_port=8443)
        with self.assertRaisesRegex(ValueError, "web-interface-port"):
            _config(
                control_panel_port=3773,
                agent_tools=["codex"],
                web_interfaces=["t3code"],
                web_interface_port=3773,
            )

    def test_password_requires_enabled_panel(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --control-panel"):
            SetupConfig(
                host="agent-vm",
                username="agent",
                system_type="server_dev",
                control_panel_auth_password="secret",
            )

    def test_panel_step_is_capability_gated(self) -> None:
        enabled_names = [name for name, _step in build_server_steps(_config())]
        disabled_names = [
            name
            for name, _step in build_server_steps(
                SetupConfig(
                    host="agent-vm",
                    username="agent",
                    system_type="server_dev",
                )
            )
        ]

        self.assertTrue(any("control panel" in name for name in enabled_names))
        self.assertFalse(any("control panel" in name for name in disabled_names))

    def test_server_lite_removal_reconciles_the_firewall(self) -> None:
        names = [
            name
            for name, _step in build_server_steps(
                SetupConfig(
                    host="agent-vm",
                    username="agent",
                    system_type="server_lite",
                    disable_control_panel=True,
                )
            )
        ]

        self.assertIn("Configuring firewall for requested web ports", names)
        self.assertIn("Removing infra-tools control panel", names)

    def test_access_summary_includes_complete_panel_link(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            print_service_access_summary(
                _config(host="2001:db8::20", control_panel_port=9443, enable_ssl=True)
            )

        self.assertIn(
            "Control panel: https://[2001:db8::20]:9443/",
            output.getvalue(),
        )


class ControlPanelPayloadTest(unittest.TestCase):
    def test_hashes_password_without_putting_it_in_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = SimpleNamespace(returncode=0, stdout="$6$salt$hash\n")
            config = _config(control_panel_auth_password="very-secret")
            with patch(
                "lib.setup_common.subprocess.run", return_value=completed
            ) as mock_run:
                prepare_control_panel_payload(config, temporary)

            with open(
                os.path.join(temporary, "htpasswd"), encoding="utf-8"
            ) as file_obj:
                self.assertEqual(file_obj.read(), "agent:$6$salt$hash\n")
            self.assertEqual(mock_run.call_args.args[0], ["openssl", "passwd", "-6", "-stdin"])
            self.assertEqual(mock_run.call_args.kwargs["input"], "very-secret\n")


class ControlPanelLifecycleTest(unittest.TestCase):
    def test_preserved_auth_must_match_the_setup_username(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = os.path.join(temporary, "config")
            os.mkdir(config_dir)
            auth_file = os.path.join(config_dir, "htpasswd")
            with open(auth_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("old-user:$6$salt$hash\n")

            with patch.multiple(
                "common.control_panel_steps",
                CONTROL_PANEL_CONFIG_DIR=config_dir,
                CONTROL_PANEL_AUTH_FILE=auth_file,
                CONTROL_PANEL_PAYLOAD_FILE=os.path.join(temporary, "missing"),
            ):
                with self.assertRaisesRegex(RuntimeError, "setup username"):
                    _install_auth_file("agent")

    def test_new_payload_replaces_auth_for_a_renamed_setup_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = os.path.join(temporary, "config")
            payload_dir = os.path.join(temporary, "payload")
            os.mkdir(config_dir)
            os.mkdir(payload_dir)
            auth_file = os.path.join(config_dir, "htpasswd")
            payload_file = os.path.join(payload_dir, "htpasswd")
            with open(auth_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("old-user:$6$salt$old\n")
            with open(payload_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("agent:$6$salt$new\n")
            account = SimpleNamespace(pw_gid=os.getgid())

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_CONFIG_DIR=config_dir,
                    CONTROL_PANEL_AUTH_FILE=auth_file,
                    CONTROL_PANEL_PAYLOAD_FILE=payload_file,
                ),
                patch(
                    "common.control_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch("common.control_panel_steps.os.chown"),
            ):
                changed, previous = _install_auth_file("agent")

            self.assertTrue(changed)
            self.assertEqual(previous, b"old-user:$6$salt$old\n")
            with open(auth_file, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "agent:$6$salt$new\n")

    def test_nginx_reload_failure_restores_previous_site(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = os.path.join(temporary, "site")
            link = os.path.join(temporary, "enabled")
            old_content = "# Managed by infra_tools control panel\nold\n"
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write(old_content)
            os.symlink(site, link)

            def run_command(command: str, **kwargs: object) -> SimpleNamespace:
                if command == "systemctl reload nginx" and kwargs.get("check") is True:
                    raise RuntimeError("reload failed")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_NGINX_SITE=site,
                    CONTROL_PANEL_NGINX_LINK=link,
                ),
                patch(
                    "common.control_panel_steps.run",
                    side_effect=run_command,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "reload failed"):
                    _write_nginx_site(
                        "# Managed by infra_tools control panel\nnew\n"
                    )

            with open(site, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), old_content)
            self.assertEqual(os.path.realpath(link), site)

    def test_service_activation_failure_removes_new_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "control-panel.service")
            account = SimpleNamespace(pw_uid=os.getuid())

            def run_command(command: str, **_kwargs: object) -> SimpleNamespace:
                if command == "systemctl restart infra-tools-control-panel.service":
                    raise RuntimeError("service failed")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_SERVICE_FILE=service_file,
                ),
                patch(
                    "common.control_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch(
                    "common.control_panel_steps.run",
                    side_effect=run_command,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "service failed"):
                    _configure_service(_config(), "/home/agent")

            self.assertFalse(os.path.exists(service_file))

    def test_service_unit_quotes_home_and_includes_hardening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "control-panel.service")
            socket_path = os.path.join(temporary, "http.sock")
            with open(socket_path, "w", encoding="utf-8"):
                pass
            account = SimpleNamespace(pw_uid=os.getuid())

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_SERVICE_FILE=service_file,
                    CONTROL_PANEL_SOCKET=socket_path,
                ),
                patch(
                    "common.control_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch(
                    "common.control_panel_steps.run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ),
                patch(
                    "common.control_panel_steps.is_service_active",
                    return_value=True,
                ),
            ):
                _configure_service(_config(), "/home/agent workspace")

            with open(service_file, encoding="utf-8") as file_obj:
                content = file_obj.read()
            self.assertIn('Environment="HOME=/home/agent workspace"', content)
            self.assertIn("ProtectControlGroups=true", content)
            self.assertIn("LockPersonality=true", content)

    def test_removal_refuses_an_unmanaged_nginx_site_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = os.path.join(temporary, "site")
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write("server { listen 9443; }\n")

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_SERVICE_FILE=os.path.join(temporary, "service"),
                    CONTROL_PANEL_CONFIG_DIR=os.path.join(temporary, "config"),
                    CONTROL_PANEL_MANIFEST=os.path.join(temporary, "manifest"),
                    CONTROL_PANEL_AUTH_FILE=os.path.join(temporary, "auth"),
                    CONTROL_PANEL_NGINX_SITE=site,
                    CONTROL_PANEL_NGINX_LINK=os.path.join(temporary, "link"),
                ),
                patch("common.control_panel_steps.run") as mock_run,
            ):
                with self.assertRaisesRegex(RuntimeError, "unmanaged.*Nginx site"):
                    remove_control_panel()

            self.assertTrue(os.path.exists(site))
            mock_run.assert_not_called()

    def test_removal_cleans_stale_nginx_files_when_nginx_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = os.path.join(temporary, "site")
            link = os.path.join(temporary, "link")
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write("# Managed by infra_tools control panel\n")
            os.symlink(site, link)

            with (
                patch.multiple(
                    "common.control_panel_steps",
                    CONTROL_PANEL_SERVICE_FILE=os.path.join(temporary, "service"),
                    CONTROL_PANEL_CONFIG_DIR=os.path.join(temporary, "config"),
                    CONTROL_PANEL_MANIFEST=os.path.join(temporary, "manifest"),
                    CONTROL_PANEL_AUTH_FILE=os.path.join(temporary, "auth"),
                    CONTROL_PANEL_NGINX_SITE=site,
                    CONTROL_PANEL_NGINX_LINK=link,
                ),
                patch(
                    "common.control_panel_steps.shutil.which",
                    return_value=None,
                ),
                patch("common.control_panel_steps.run") as mock_run,
                patch("common.control_panel_steps.remove_nginx_auth_failure_ban"),
            ):
                remove_control_panel()

            self.assertFalse(os.path.lexists(site))
            self.assertFalse(os.path.lexists(link))
            mock_run.assert_not_called()


class ControlPanelRenderingTest(unittest.TestCase):
    @staticmethod
    def _t3_manifest() -> dict[str, object]:
        return {
            "version": 1,
            "title": "Coding VM",
            "host": "agent-vm.local",
            "system_type": "agent_code_vm",
            "username": "agent",
            "services": [],
            "access": [],
            "features": {"t3_update": True},
        }

    def test_manifest_reflects_installed_capabilities(self) -> None:
        config = _config(
            enable_rdp=True,
            enable_samba=True,
            samba_shares=[["write", "work", "/srv/work", "agent"]],
            agent_tools=["codex"],
            web_interfaces=["t3code"],
            friendly_name="Coding VM",
        )

        manifest = build_control_panel_manifest(
            config, ["localhost", "agent-vm.local", "192.0.2.30"]
        )

        self.assertEqual(manifest["title"], "Coding VM")
        self.assertTrue(manifest["features"]["t3_update"])
        values = [record["value"] for record in manifest["access"]]
        self.assertIn("ssh agent@agent-vm.local", values)
        self.assertIn("agent-vm.local:3389", values)
        self.assertIn("smb://agent-vm.local/work_write", values)

    def test_nginx_requires_basic_auth_and_can_share_tls_certificate(self) -> None:
        rendered = render_control_panel_nginx(
            ["agent-vm.local", "192.0.2.30"],
            443,
            cert_path="/etc/infra-web/tls/internal.crt",
            key_path="/etc/infra-web/tls/internal.key",
        )

        self.assertIn("listen 443 ssl", rendered)
        self.assertIn("auth_basic_user_file", rendered)
        self.assertIn("limit_req zone=infra_tools_control_panel_auth", rendered)
        self.assertIn("proxy_pass http://unix:/run/infra-tools-control-panel/http.sock:/", rendered)
        self.assertIn("ssl_certificate /etc/infra-web/tls/internal.crt", rendered)

    def test_page_escapes_content_and_only_shows_available_action(self) -> None:
        manifest = {
            "version": 1,
            "title": "Agent <VM>",
            "host": "agent-vm.local",
            "system_type": "agent_code_vm",
            "username": "agent",
            "services": [
                {
                    "label": "T3 Code",
                    "url": "https://agent-vm.local:3773/",
                    "description": "Coding UI",
                }
            ],
            "access": [{"label": "SSH", "value": "ssh agent@agent-vm.local"}],
            "features": {"t3_update": True},
        }
        with (
            patch(
                "common.service_tools.control_panel_service.discover_infra_web_services",
                return_value=[],
            ),
            patch(
                "common.service_tools.control_panel_service.os.path.isdir",
                return_value=True,
            ),
        ):
            rendered = render_page(ControlPanelState(manifest))

        self.assertIn("Agent &lt;VM&gt;", rendered)
        self.assertIn("Update T3 Code", rendered)
        self.assertIn("ssh agent@agent-vm.local", rendered)
        self.assertNotIn("Agent <VM>", rendered)

    def test_rejects_credential_bearing_service_urls(self) -> None:
        self.assertIsNone(_safe_url("https://user:password@example.test/"))
        self.assertEqual(
            _safe_url("https://example.test:8443/"),
            "https://example.test:8443/",
        )

    def test_t3_update_uses_the_user_launcher_for_readiness(self) -> None:
        state = ControlPanelState(self._t3_manifest())
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with (
            patch(
                "common.service_tools.control_panel_service.os.path.expanduser",
                return_value="/home/agent",
            ),
            patch(
                "common.service_tools.control_panel_service.shutil.which",
                return_value="/home/agent/.local/bin/infra-tools",
            ) as mock_which,
            patch(
                "common.service_tools.control_panel_service.subprocess.run",
                side_effect=[completed, completed],
            ) as mock_run,
        ):
            state._run_t3_update()

        launcher_path = mock_run.call_args_list[1].kwargs["env"]["PATH"]
        self.assertTrue(launcher_path.startswith("/home/agent/.local/bin:"))
        mock_which.assert_called_once_with("infra-tools", path=launcher_path)
        self.assertEqual(state.action_status, "complete")

    def test_t3_update_fails_closed_without_readiness_command(self) -> None:
        state = ControlPanelState(self._t3_manifest())
        completed = SimpleNamespace(returncode=0, stdout="updated\n", stderr="")
        with (
            patch(
                "common.service_tools.control_panel_service.subprocess.run",
                return_value=completed,
            ),
            patch(
                "common.service_tools.control_panel_service.shutil.which",
                return_value=None,
            ),
        ):
            state._run_t3_update()

        self.assertEqual(state.action_status, "failed")
        self.assertIn("readiness command is unavailable", state.action_message)

    def test_t3_update_guard_records_unexpected_failures(self) -> None:
        state = ControlPanelState(self._t3_manifest())
        with patch.object(
            state,
            "_run_t3_update",
            side_effect=RuntimeError("unexpected"),
        ):
            state._run_t3_update_guarded()

        self.assertEqual(state.action_status, "failed")
        self.assertEqual(state.action_message, "T3 Code update stopped unexpectedly.")
        self.assertIn("RuntimeError: unexpected", state.action_output)


if __name__ == "__main__":
    unittest.main()
