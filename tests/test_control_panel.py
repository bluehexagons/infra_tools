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
    build_control_panel_manifest,
    control_panel_url,
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


class ControlPanelRenderingTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
