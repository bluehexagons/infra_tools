"""Tests for the optional authenticated infra-tools web panel."""

from __future__ import annotations

import json
import http.client
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, nullcontext, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from common.web_panel_steps import (
    _configure_audit_exporter,
    _configure_service,
    _install_auth_file,
    _install_ingest_token,
    _write_nginx_site,
    build_web_panel_manifest,
    web_panel_url,
    remove_web_panel,
    render_web_panel_nginx,
)
from common.service_tools.web_panel_audit_export import collect_audit_snapshot
from common.service_tools.web_panel_service import (
    WebPanelState,
    WebPanelHandler,
    _ThreadingTCPHTTPServer,
    _internal_web_landing_service,
    _linux_trust_script,
    _macos_trust_script,
    _safe_url,
    collect_system_overview,
    discover_certificate_trust,
    discover_infra_web_services,
    render_page,
)
from common.web_panel_events import (
    WEB_PANEL_NOTIFICATION_ENDPOINT,
    validate_notification_payload,
)
from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.display import print_service_access_summary
from lib.setup_common import prepare_web_panel_payload
from plugins.server import build_server_steps


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "agent-vm",
        "username": "agent",
        "system_type": "server_dev",
        "web_panel_port": 80,
    }
    values.update(overrides)
    return SetupConfig(**values)


def _t3_doctor_output(**overrides: bool) -> str:
    checks = {
        "service_active": True,
        "service_enabled": True,
        "runtime": True,
        "native_runtime": True,
        "wrapper": True,
        "pairing_helper": True,
        "endpoint": True,
        "git_identity": False,
        "t3_agent_skill": True,
        "gh_authenticated": False,
        "git_credential_helper": False,
    }
    checks.update(overrides)
    return json.dumps(
        [
            {
                "capability": "t3code",
                "healthy": all(checks.values()),
                "checks": checks,
                "fixes": [],
            }
        ]
    )


class WebPanelConfigTest(unittest.TestCase):
    def test_cli_defaults_to_http_or_https_standard_port(self) -> None:
        parser = create_setup_argument_parser("test")

        http = SetupConfig.from_args(
            parser.parse_args(["agent-vm", "agent", "--web-panel"]),
            "server_dev",
        )
        https = SetupConfig.from_args(
            parser.parse_args(
                ["agent-vm", "agent", "--web-panel", "--ssl"]
            ),
            "server_dev",
        )

        self.assertEqual(http.web_panel_port, 80)
        self.assertEqual(https.web_panel_port, 443)
        self.assertEqual(web_panel_url(http), "http://agent-vm/")
        self.assertEqual(web_panel_url(https), "https://agent-vm/")

    def test_cli_accepts_custom_port_and_keeps_password_transient(self) -> None:
        parser = create_setup_argument_parser("test")
        config = SetupConfig.from_args(
            parser.parse_args(
                [
                    "agent-vm",
                    "agent",
                    "--web-panel",
                    "9443",
                    "--web-panel-password",
                    "panel-secret",
                ]
            ),
            "server_dev",
        )

        self.assertEqual(config.web_panel_port, 9443)
        self.assertEqual(config.web_panel_auth_password, "panel-secret")
        self.assertNotIn("panel-secret", " ".join(config.to_remote_args()))
        self.assertNotIn("panel-secret", " ".join(config.to_setup_command()))
        self.assertNotIn("panel-secret", str(config.to_dict()))

    def test_explicit_zero_port_is_rejected(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            ["agent-vm", "agent", "--web-panel", "0"]
        )

        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            SetupConfig.from_args(args, "server_dev")

    def test_remote_payload_flag_is_serialized_without_secret(self) -> None:
        config = _config(web_panel_payload=True)
        remote = " ".join(config.to_remote_args())

        self.assertIn("--web-panel 80", remote)
        self.assertIn("--web-panel-payload", remote)
        self.assertNotIn("web_panel_payload", config.to_dict())

    def test_notification_ingest_requires_https_and_is_forwarded(self) -> None:
        parser = create_setup_argument_parser("test")
        config = SetupConfig.from_args(
            parser.parse_args(
                [
                    "agent-vm",
                    "agent",
                    "--web-panel",
                    "--ssl",
                    "--web-panel-notification-ingest",
                ]
            ),
            "server_dev",
        )

        self.assertTrue(config.web_panel_notification_ingest)
        self.assertIn("--web-panel-notification-ingest", config.to_remote_args())
        self.assertIn("--web-panel-notification-ingest", config.to_setup_command())
        self.assertTrue(config.to_dict()["web_panel_notification_ingest"])

    def test_notification_ingest_rejects_plaintext_panel(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --ssl"):
            _config(web_panel_notification_ingest=True)

    def test_notification_ingest_requires_a_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            _config(web_panel_notification_ingest=1, enable_ssl=True)

    def test_agent_readiness_payload_facts_are_forwarded_but_not_saved(self) -> None:
        config = _config(
            github_auth_payload=True,
            git_identity_payload=True,
        )
        remote = " ".join(config.to_remote_args())

        self.assertIn("--github-auth-payload", remote)
        self.assertIn("--git-identity-payload", remote)
        self.assertNotIn("github_auth_payload", config.to_dict())
        self.assertNotIn("git_identity_payload", config.to_dict())

    def test_rejects_reserved_and_conflicting_ports(self) -> None:
        with self.assertRaisesRegex(ValueError, "8443 is reserved"):
            _config(web_panel_port=8443)
        with self.assertRaisesRegex(ValueError, "web-interface-port"):
            _config(
                web_panel_port=3773,
                agent_tools=["codex"],
                web_interfaces=["t3code"],
                web_interface_port=3773,
            )

    def test_password_requires_enabled_panel(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --web-panel"):
            SetupConfig(
                host="agent-vm",
                username="agent",
                system_type="server_dev",
                web_panel_auth_password="secret",
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

        self.assertTrue(any("web panel" in name for name in enabled_names))
        self.assertFalse(any("web panel" in name for name in disabled_names))

    def test_server_lite_removal_reconciles_the_firewall(self) -> None:
        names = [
            name
            for name, _step in build_server_steps(
                SetupConfig(
                    host="agent-vm",
                    username="agent",
                    system_type="server_lite",
                    disable_web_panel=True,
                )
            )
        ]

        self.assertIn("Configuring firewall for requested web ports", names)
        self.assertIn("Removing infra-tools web panel", names)

    def test_access_summary_includes_complete_panel_link(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            print_service_access_summary(
                _config(host="2001:db8::20", web_panel_port=9443, enable_ssl=True)
            )

        self.assertIn(
            "Web panel: https://[2001:db8::20]:9443/",
            output.getvalue(),
        )


class WebPanelPayloadTest(unittest.TestCase):
    def test_hashes_password_without_putting_it_in_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = SimpleNamespace(returncode=0, stdout="$6$salt$hash\n")
            config = _config(web_panel_auth_password="very-secret")
            with patch(
                "lib.setup_common.subprocess.run", return_value=completed
            ) as mock_run:
                prepare_web_panel_payload(config, temporary)

            with open(
                os.path.join(temporary, "htpasswd"), encoding="utf-8"
            ) as file_obj:
                self.assertEqual(file_obj.read(), "agent:$6$salt$hash\n")
            self.assertEqual(mock_run.call_args.args[0], ["openssl", "passwd", "-6", "-stdin"])
            self.assertEqual(mock_run.call_args.kwargs["input"], "very-secret\n")


class WebPanelLifecycleTest(unittest.TestCase):
    def test_service_script_loads_when_launched_outside_the_source_tree(self) -> None:
        script = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "common",
                "service_tools",
                "web_panel_service.py",
            )
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, script, "--help"],
                cwd=temporary,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Serve the infra-tools web panel", result.stdout)

    def test_preserved_auth_must_match_the_setup_username(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = os.path.join(temporary, "config")
            os.mkdir(config_dir)
            auth_file = os.path.join(config_dir, "htpasswd")
            with open(auth_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("old-user:$6$salt$hash\n")

            with patch.multiple(
                "common.web_panel_steps",
                WEB_PANEL_CONFIG_DIR=config_dir,
                WEB_PANEL_AUTH_FILE=auth_file,
                WEB_PANEL_PAYLOAD_FILE=os.path.join(temporary, "missing"),
            ):
                with self.assertRaisesRegex(RuntimeError, "setup username"):
                    _install_auth_file("agent")

    def test_ingest_token_is_generated_once_and_removed_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_path = os.path.join(temporary, "ingest.token")
            account = SimpleNamespace(pw_gid=os.getgid())
            with (
                patch(
                    "common.web_panel_steps.WEB_PANEL_INGEST_TOKEN",
                    token_path,
                ),
                patch(
                    "common.web_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch("common.web_panel_steps.os.chown"),
            ):
                self.assertTrue(_install_ingest_token(True))
                with open(token_path, encoding="utf-8") as file_obj:
                    first = file_obj.read()
                self.assertFalse(_install_ingest_token(True))
                with open(token_path, encoding="utf-8") as file_obj:
                    second = file_obj.read()
                self.assertEqual(first, second)
                self.assertTrue(_install_ingest_token(False))

            self.assertFalse(os.path.exists(token_path))

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
                    "common.web_panel_steps",
                    WEB_PANEL_CONFIG_DIR=config_dir,
                    WEB_PANEL_AUTH_FILE=auth_file,
                    WEB_PANEL_PAYLOAD_FILE=payload_file,
                ),
                patch(
                    "common.web_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch("common.web_panel_steps.os.chown"),
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
            old_content = "# Managed by infra_tools web panel\nold\n"
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write(old_content)
            os.symlink(site, link)

            def run_command(command: str, **kwargs: object) -> SimpleNamespace:
                if command == "systemctl reload nginx" and kwargs.get("check") is True:
                    raise RuntimeError("reload failed")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_NGINX_SITE=site,
                    WEB_PANEL_NGINX_LINK=link,
                ),
                patch(
                    "common.web_panel_steps.run",
                    side_effect=run_command,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "reload failed"):
                    _write_nginx_site(
                        "# Managed by infra_tools web panel\nnew\n"
                    )

            with open(site, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), old_content)
            self.assertEqual(os.path.realpath(link), site)

    def test_service_activation_failure_removes_new_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "web-panel.service")
            account = SimpleNamespace(pw_uid=os.getuid())

            def run_command(command: str, **_kwargs: object) -> SimpleNamespace:
                if command == "systemctl restart infra-tools-web-panel.service":
                    raise RuntimeError("service failed")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_SERVICE_FILE=service_file,
                ),
                patch(
                    "common.web_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch(
                    "common.web_panel_steps.run",
                    side_effect=run_command,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "service failed"):
                    _configure_service(_config(), "/home/agent")

            self.assertFalse(os.path.exists(service_file))

    def test_service_unit_quotes_home_and_includes_hardening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "web-panel.service")
            socket_path = os.path.join(temporary, "http.sock")
            with open(socket_path, "w", encoding="utf-8"):
                pass
            account = SimpleNamespace(pw_uid=os.getuid())

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_SERVICE_FILE=service_file,
                    WEB_PANEL_SOCKET=socket_path,
                ),
                patch(
                    "common.web_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch(
                    "common.web_panel_steps.run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ),
                patch(
                    "common.web_panel_steps.is_service_active",
                    return_value=True,
                ),
            ):
                _configure_service(_config(), "/home/agent workspace")

            with open(service_file, encoding="utf-8") as file_obj:
                content = file_obj.read()
            self.assertIn('Environment="HOME=/home/agent workspace"', content)
            self.assertIn("ProtectControlGroups=true", content)
            self.assertIn("LockPersonality=true", content)

    def test_audit_exporter_is_root_only_with_one_writable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "audit.service")
            timer_file = os.path.join(temporary, "audit.timer")
            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_AUDIT_SERVICE_FILE=service_file,
                    WEB_PANEL_AUDIT_TIMER_FILE=timer_file,
                    WEB_PANEL_AUDIT_DIR="/var/lib/infra_tools/web-panel/audit",
                    WEB_PANEL_AUDIT_SNAPSHOT=(
                        "/var/lib/infra_tools/web-panel/audit/events.json"
                    ),
                ),
                patch(
                    "common.web_panel_steps.run",
                    return_value=SimpleNamespace(
                        returncode=0, stdout="", stderr=""
                    ),
                ),
            ):
                self.assertTrue(_configure_audit_exporter())

            with open(service_file, encoding="utf-8") as file_obj:
                service = file_obj.read()
            with open(timer_file, encoding="utf-8") as file_obj:
                timer = file_obj.read()
            self.assertIn("User=root", service)
            self.assertIn("ProtectSystem=strict", service)
            self.assertIn(
                "ReadWritePaths=/var/lib/infra_tools/web-panel/audit",
                service,
            )
            self.assertIn("OnUnitActiveSec=5min", timer)

    def test_service_socket_timeout_includes_systemd_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_file = os.path.join(temporary, "web-panel.service")
            account = SimpleNamespace(pw_uid=os.getuid())

            def run_command(command: str, **_kwargs: object) -> SimpleNamespace:
                if command.startswith("systemctl status "):
                    return SimpleNamespace(
                        returncode=3,
                        stdout="ModuleNotFoundError: No module named 'common'",
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_SERVICE_FILE=service_file,
                    WEB_PANEL_SOCKET=os.path.join(temporary, "missing.sock"),
                ),
                patch(
                    "common.web_panel_steps.pwd.getpwnam",
                    return_value=account,
                ),
                patch(
                    "common.web_panel_steps.run",
                    side_effect=run_command,
                ),
                patch(
                    "common.web_panel_steps.is_service_active",
                    return_value=False,
                ),
                patch("common.web_panel_steps.time.sleep"),
            ):
                with self.assertRaisesRegex(RuntimeError, "ModuleNotFoundError"):
                    _configure_service(_config(), "/home/agent")

    def test_removal_refuses_an_unmanaged_nginx_site_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = os.path.join(temporary, "site")
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write("server { listen 9443; }\n")

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_SERVICE_FILE=os.path.join(temporary, "service"),
                    WEB_PANEL_CONFIG_DIR=os.path.join(temporary, "config"),
                    WEB_PANEL_MANIFEST=os.path.join(temporary, "manifest"),
                    WEB_PANEL_AUTH_FILE=os.path.join(temporary, "auth"),
                    WEB_PANEL_INGEST_TOKEN=os.path.join(temporary, "token"),
                    WEB_PANEL_DATA_DIR=os.path.join(temporary, "data"),
                    WEB_PANEL_AUDIT_DIR=os.path.join(temporary, "data", "audit"),
                    WEB_PANEL_NOTIFICATION_DIR=os.path.join(
                        temporary, "data", "notifications"
                    ),
                    WEB_PANEL_AUDIT_SNAPSHOT=os.path.join(
                        temporary, "data", "audit", "events.json"
                    ),
                    WEB_PANEL_NOTIFICATION_LOG=os.path.join(
                        temporary, "data", "notifications", "events.jsonl"
                    ),
                    WEB_PANEL_AUDIT_SERVICE_FILE=os.path.join(
                        temporary, "audit.service"
                    ),
                    WEB_PANEL_AUDIT_TIMER_FILE=os.path.join(
                        temporary, "audit.timer"
                    ),
                    WEB_PANEL_NGINX_SITE=site,
                    WEB_PANEL_NGINX_LINK=os.path.join(temporary, "link"),
                ),
                patch("common.web_panel_steps.run") as mock_run,
            ):
                with self.assertRaisesRegex(RuntimeError, "unmanaged.*Nginx site"):
                    remove_web_panel()

            self.assertTrue(os.path.exists(site))
            mock_run.assert_not_called()

    def test_removal_cleans_stale_nginx_files_when_nginx_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = os.path.join(temporary, "site")
            link = os.path.join(temporary, "link")
            with open(site, "w", encoding="utf-8") as file_obj:
                file_obj.write("# Managed by infra_tools web panel\n")
            os.symlink(site, link)

            with (
                patch.multiple(
                    "common.web_panel_steps",
                    WEB_PANEL_SERVICE_FILE=os.path.join(temporary, "service"),
                    WEB_PANEL_CONFIG_DIR=os.path.join(temporary, "config"),
                    WEB_PANEL_MANIFEST=os.path.join(temporary, "manifest"),
                    WEB_PANEL_AUTH_FILE=os.path.join(temporary, "auth"),
                    WEB_PANEL_INGEST_TOKEN=os.path.join(temporary, "token"),
                    WEB_PANEL_DATA_DIR=os.path.join(temporary, "data"),
                    WEB_PANEL_AUDIT_DIR=os.path.join(temporary, "data", "audit"),
                    WEB_PANEL_NOTIFICATION_DIR=os.path.join(
                        temporary, "data", "notifications"
                    ),
                    WEB_PANEL_AUDIT_SNAPSHOT=os.path.join(
                        temporary, "data", "audit", "events.json"
                    ),
                    WEB_PANEL_NOTIFICATION_LOG=os.path.join(
                        temporary, "data", "notifications", "events.jsonl"
                    ),
                    WEB_PANEL_AUDIT_SERVICE_FILE=os.path.join(
                        temporary, "audit.service"
                    ),
                    WEB_PANEL_AUDIT_TIMER_FILE=os.path.join(
                        temporary, "audit.timer"
                    ),
                    WEB_PANEL_NGINX_SITE=site,
                    WEB_PANEL_NGINX_LINK=link,
                ),
                patch(
                    "common.web_panel_steps.shutil.which",
                    return_value=None,
                ),
                patch("common.web_panel_steps.run") as mock_run,
                patch("common.web_panel_steps.remove_nginx_auth_failure_ban"),
            ):
                remove_web_panel()

            self.assertFalse(os.path.lexists(site))
            self.assertFalse(os.path.lexists(link))
            mock_run.assert_not_called()


class WebPanelRenderingTest(unittest.TestCase):
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
            "features": {
                "t3_update": True,
                "t3_github_readiness": False,
                "t3_git_identity_readiness": False,
            },
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

        manifest = build_web_panel_manifest(
            config, ["localhost", "agent-vm.local", "192.0.2.30"]
        )

        self.assertEqual(manifest["title"], "Coding VM")
        self.assertTrue(manifest["features"]["t3_update"])
        self.assertFalse(manifest["features"]["t3_github_readiness"])
        self.assertFalse(manifest["features"]["t3_git_identity_readiness"])
        values = [record["value"] for record in manifest["access"]]
        self.assertIn("ssh agent@agent-vm.local", values)
        self.assertIn("agent-vm.local:3389", values)
        self.assertIn("smb://agent-vm.local/work_write", values)

    def test_manifest_requires_github_checks_only_for_staged_credentials(self) -> None:
        manifest = build_web_panel_manifest(
            _config(
                agent_tools=["gh", "codex"],
                web_interfaces=["t3code"],
                git_access="read-write",
                agent_payload=True,
                github_auth_payload=True,
                git_identity_payload=True,
            ),
            ["agent-vm.local"],
        )

        self.assertTrue(manifest["features"]["t3_github_readiness"])
        self.assertTrue(manifest["features"]["t3_git_identity_readiness"])

    def test_nginx_requires_basic_auth_and_can_share_tls_certificate(self) -> None:
        rendered = render_web_panel_nginx(
            ["agent-vm.local", "192.0.2.30"],
            443,
            cert_path="/etc/infra-web/tls/internal.crt",
            key_path="/etc/infra-web/tls/internal.key",
        )

        self.assertIn("listen 443 ssl", rendered)
        self.assertIn("auth_basic_user_file", rendered)
        self.assertIn("rate=120r/m", rendered)
        self.assertIn("limit_req zone=infra_tools_web_panel_auth", rendered)
        self.assertIn("proxy_pass http://unix:/run/infra-tools-web-panel/http.sock:/", rendered)
        self.assertIn("ssl_certificate /etc/infra-web/tls/internal.crt", rendered)

    def test_nginx_ingest_route_bypasses_basic_auth_but_has_its_own_limits(self) -> None:
        rendered = render_web_panel_nginx(
            ["agent-vm.local"],
            443,
            cert_path="/etc/infra-web/tls/internal.crt",
            key_path="/etc/infra-web/tls/internal.key",
            notification_ingest=True,
        )

        self.assertIn(f"location = {WEB_PANEL_NOTIFICATION_ENDPOINT}", rendered)
        self.assertIn("auth_basic off", rendered)
        self.assertIn("rate=30r/m", rendered)
        self.assertIn("client_max_body_size 64k", rendered)


class WebPanelEventTest(unittest.TestCase):
    _t3_manifest = staticmethod(WebPanelRenderingTest._t3_manifest)

    @staticmethod
    def _notification() -> dict[str, object]:
        return {
            "schema_version": 2,
            "event": {
                "type": "backup",
                "state": "firing",
                "status": "warning",
                "deduplication_key": "backup:agent-2",
            },
            "operator": {
                "subject": "Backup needs attention",
                "job": "backup",
                "system": "agent-2",
                "what_happened": "The latest backup did not complete.",
                "suggested_actions": ["Check the backup service"],
                "details": "Exit status 1",
            },
            "data": {"attempt": 3},
        }

    def test_ingest_accepts_valid_bearer_request_and_persists_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_path = os.path.join(temporary, "token")
            notification_path = os.path.join(temporary, "events.jsonl")
            with open(token_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("a" * 43 + "\n")
            manifest = {
                **WebPanelRenderingTest._t3_manifest(),
                "features": {"t3_update": False, "notification_ingest": True},
            }
            state = WebPanelState(
                manifest,
                audit_snapshot_path=os.path.join(temporary, "audit.json"),
                notification_log_path=notification_path,
                ingest_token_path=token_path,
            )
            WebPanelHandler.state = state
            server = _ThreadingTCPHTTPServer(("127.0.0.1", 0), WebPanelHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=5
                )
                body = json.dumps(self._notification())
                connection.request(
                    "POST",
                    WEB_PANEL_NOTIFICATION_ENDPOINT,
                    body=body,
                    headers={
                        "Authorization": "Bearer " + "a" * 43,
                        "Content-Type": "application/json",
                        "X-Forwarded-Proto": "https",
                        "X-Real-IP": "192.0.2.45",
                    },
                )
                response = connection.getresponse()
                response_body = response.read()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 202, response_body)
            events = state.notification_events()
            self.assertEqual(events[0]["source_ip"], "192.0.2.45")
            self.assertEqual(
                events[0]["notification"]["operator"]["subject"],
                "Backup needs attention",
            )

    def test_notification_schema_version_must_be_an_integer(self) -> None:
        payload = self._notification()
        payload["schema_version"] = 2.0

        with self.assertRaisesRegex(ValueError, "schema_version 2"):
            validate_notification_payload(payload)

    def test_ingest_rejects_bad_token_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_path = os.path.join(temporary, "token")
            notification_path = os.path.join(temporary, "events.jsonl")
            with open(token_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("a" * 43 + "\n")
            state = WebPanelState(
                {
                    **WebPanelRenderingTest._t3_manifest(),
                    "features": {"t3_update": False, "notification_ingest": True},
                },
                notification_log_path=notification_path,
                ingest_token_path=token_path,
            )
            WebPanelHandler.state = state
            server = _ThreadingTCPHTTPServer(("127.0.0.1", 0), WebPanelHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=5
                )
                connection.request(
                    "POST",
                    WEB_PANEL_NOTIFICATION_ENDPOINT,
                    body=json.dumps(self._notification()),
                    headers={
                        "Authorization": "Bearer " + "b" * 43,
                        "Content-Type": "application/json",
                        "X-Forwarded-Proto": "https",
                    },
                )
                response = connection.getresponse()
                response.read()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 401)
            self.assertFalse(os.path.exists(notification_path))

    @patch("common.service_tools.web_panel_audit_export.shutil.which")
    @patch("common.service_tools.web_panel_audit_export.subprocess.run")
    def test_audit_export_is_sanitized_and_bounded(
        self, mock_run: unittest.mock.MagicMock, mock_which: unittest.mock.MagicMock
    ) -> None:
        mock_which.return_value = "/usr/sbin/ausearch"
        record = (
            "type=SYSCALL msg=audit(1788361200.0:42): "
            'syscall=openat auid=agent exe="/usr/bin/sudo" proctitle=SECRET\n'
            'type=PATH msg=audit(1788361200.0:42): name="/etc/sudoers"\n----\n'
        )

        def run_audit(*_args: object, **kwargs: object) -> SimpleNamespace:
            kwargs["stdout"].write(record.encode("utf-8"))
            return SimpleNamespace(returncode=0)

        mock_run.side_effect = run_audit

        snapshot = collect_audit_snapshot()

        self.assertEqual(snapshot["status"], "ok")
        self.assertLessEqual(len(snapshot["events"]), 100)
        serialized = json.dumps(snapshot)
        self.assertIn("/etc/sudoers", serialized)
        self.assertNotIn("SECRET", serialized)

    def test_page_renders_audit_and_remote_notification_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_path = os.path.join(temporary, "token")
            audit_path = os.path.join(temporary, "audit.json")
            notification_path = os.path.join(temporary, "events.jsonl")
            with open(token_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("a" * 43 + "\n")
            with open(audit_path, "w", encoding="utf-8") as file_obj:
                json.dump(
                    {
                        "version": 1,
                        "generated_at": "2026-09-02T12:00:00+00:00",
                        "status": "ok",
                        "events": [
                            {
                                "key": "sudoers",
                                "meaning": "Administrator access policy changed",
                                "severity": "warning",
                                "timestamp": "2026-09-02T11:59:00+00:00",
                                "paths": ["/etc/sudoers"],
                            }
                        ],
                    },
                    file_obj,
                )
            with open(notification_path, "w", encoding="utf-8") as file_obj:
                json.dump(
                    {
                        "received_at": "2026-09-02T12:01:00+00:00",
                        "source_ip": "192.0.2.45",
                        "notification": {
                            **self._notification(),
                            "operator": {
                                **self._notification()["operator"],
                                "subject": "Backup <failed>",
                            },
                        },
                    },
                    file_obj,
                )
                file_obj.write("\n")
            state = WebPanelState(
                {
                    **self._t3_manifest(),
                    "features": {"t3_update": False, "notification_ingest": True},
                },
                audit_snapshot_path=audit_path,
                notification_log_path=notification_path,
                ingest_token_path=token_path,
            )
            with (
                patch(
                    "common.service_tools.web_panel_service.discover_infra_web_services",
                    return_value=[],
                ),
                patch.object(state, "system_overview", return_value=[]),
            ):
                rendered = render_page(state)

        self.assertIn("System audit log", rendered)
        self.assertIn("Administrator access policy changed", rendered)
        self.assertIn("Notifications", rendered)
        self.assertIn(WEB_PANEL_NOTIFICATION_ENDPOINT, rendered)
        self.assertIn("Backup &lt;failed&gt;", rendered)
        self.assertNotIn("Backup <failed>", rendered)

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
                "common.service_tools.web_panel_service.discover_infra_web_services",
                return_value=[],
            ),
            patch(
                "common.service_tools.web_panel_service.os.path.isdir",
                return_value=True,
            ),
        ):
            rendered = render_page(WebPanelState(manifest))

        self.assertIn("Agent &lt;VM&gt;", rendered)
        self.assertIn("infra-tools web panel", rendered)
        self.assertIn("Agent Code VM", rendered)
        self.assertIn("Update to latest", rendered)
        self.assertIn("ssh agent@agent-vm.local", rendered)
        self.assertIn("https://agent-vm.local:3773/", rendered)
        self.assertNotIn("Agent <VM>", rendered)

    def test_running_action_refreshes_until_status_changes(self) -> None:
        state = WebPanelState(self._t3_manifest())
        state.action_status = "running"
        state.action_message = "Updating T3 Code…"
        with (
            patch(
                "common.service_tools.web_panel_service.discover_infra_web_services",
                return_value=[],
            ),
            patch(
                "common.service_tools.web_panel_service.os.path.isdir",
                return_value=True,
            ),
        ):
            rendered = render_page(state)

        self.assertIn('<meta http-equiv="refresh" content="3">', rendered)
        self.assertIn("Update in progress…", rendered)
        self.assertIn('button type="submit" disabled', rendered)
        self.assertIn('role="status"', rendered)

    def test_empty_sections_explain_why_they_have_no_entries(self) -> None:
        state = WebPanelState(
            {
                **self._t3_manifest(),
                "services": [],
                "access": [],
                "features": {"t3_update": False},
            }
        )
        with patch(
            "common.service_tools.web_panel_service.discover_infra_web_services",
            return_value=[],
        ):
            rendered = render_page(state)

        self.assertIn("No hosted web services are available", rendered)
        self.assertIn("No additional access methods are configured", rendered)
        self.assertNotIn("Maintenance</h2>", rendered)

    def test_rejects_credential_bearing_service_urls(self) -> None:
        self.assertIsNone(_safe_url("https://user:password@example.test/"))
        self.assertEqual(
            _safe_url("https://example.test:8443/"),
            "https://example.test:8443/",
        )

    def test_discovers_the_web_host_landing_page_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            url_file = os.path.join(temporary, "base-url")
            with open(url_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("https://agent-vm.local:8443\n")

            service = _internal_web_landing_service(
                "/usr/local/bin/infra-web",
                url_file=url_file,
            )

        self.assertEqual(
            service,
            {
                "label": "Web hosting",
                "url": "https://agent-vm.local:8443/",
                "description": "Published sites, previews, and certificate trust",
            },
        )

    def test_web_host_landing_page_is_included_without_publications(self) -> None:
        landing = {
            "label": "Web hosting",
            "url": "https://agent-vm.local:8443/",
            "description": "Published sites, previews, and certificate trust",
        }
        with (
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/usr/local/bin/infra-web",
            ),
            patch(
                "common.service_tools.web_panel_service._internal_web_landing_service",
                return_value=landing,
            ),
            patch(
                "common.service_tools.web_panel_service._run_json",
                return_value={},
            ),
        ):
            services = discover_infra_web_services()

        self.assertEqual(services, [landing])

    def test_discovers_local_certificate_trust_metadata(self) -> None:
        with (
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/usr/local/bin/infra-web",
            ),
            patch(
                "common.service_tools.web_panel_service._run_json",
                return_value={
                    "publicly_trusted": False,
                    "url": "https://agent-vm.local:8443/infra-tools-ca.crt",
                    "sha256": "A" * 64,
                },
            ),
        ):
            trust = discover_certificate_trust()

        self.assertEqual(
            trust,
            {
                "publicly_trusted": False,
                "url": "https://agent-vm.local:8443/infra-tools-ca.crt",
                "sha256": "a" * 64,
            },
        )

    def test_rejects_certificate_metadata_with_the_wrong_download_path(self) -> None:
        with (
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/usr/local/bin/infra-web",
            ),
            patch(
                "common.service_tools.web_panel_service._run_json",
                return_value={
                    "publicly_trusted": False,
                    "url": "https://agent-vm.local:8443/not-the-ca.crt",
                    "sha256": "a" * 64,
                },
            ),
        ):
            trust = discover_certificate_trust()

        self.assertIsNone(trust)

    def test_discovers_publicly_trusted_certificate(self) -> None:
        with (
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/usr/local/bin/infra-web",
            ),
            patch(
                "common.service_tools.web_panel_service._run_json",
                return_value={"publicly_trusted": True},
            ),
        ):
            trust = discover_certificate_trust()

        self.assertEqual(trust, {"publicly_trusted": True})

    def test_page_renders_certificate_download_and_install_help(self) -> None:
        state = WebPanelState(self._t3_manifest())
        trust = {
            "publicly_trusted": False,
            "url": "https://agent-vm.local:8443/infra-tools-ca.crt",
            "sha256": "a" * 64,
        }
        with (
            patch(
                "common.service_tools.web_panel_service.discover_infra_web_services",
                return_value=[],
            ),
            patch(
                "common.service_tools.web_panel_service.discover_certificate_trust",
                return_value=trust,
            ),
            patch.object(state, "system_overview", return_value=[]),
            patch(
                "common.service_tools.web_panel_service.os.path.isdir",
                return_value=True,
            ),
        ):
            rendered = render_page(state)

        self.assertIn("Certificate trust", rendered)
        self.assertIn('<details class="trust-disclosure">', rendered)
        self.assertNotIn('<details class="trust-disclosure" open>', rendered)
        self.assertIn("Download VM CA certificate", rendered)
        self.assertIn("SHA-256 " + "a" * 64, rendered)
        self.assertIn("Download, verify, and install with a script", rendered)
        self.assertIn("Debian / Ubuntu", rendered)
        self.assertIn("Arch Linux", rendered)
        self.assertIn("Fedora / RHEL", rendered)
        self.assertIn("macOS", rendered)
        self.assertIn("Windows PowerShell", rendered)
        self.assertIn("sha256sum", rendered)
        self.assertIn("shasum -a 256", rendered)
        self.assertIn("Invoke-WebRequest", rendered)
        self.assertIn("update-ca-certificates", rendered)
        self.assertIn("/etc/ca-certificates/trust-source/anchors", rendered)
        self.assertIn("/etc/pki/ca-trust/source/anchors", rendered)
        self.assertIn("security add-trusted-cert", rendered)
        self.assertIn("/srv/infra-tools/web/infra-tools-ca.crt", rendered)
        self.assertIn("certutil.exe -user -addstore", rendered)
        self.assertIn("Manual / GUI installation", rendered)
        self.assertIn("iPhone / iPad", rendered)

    def test_certificate_install_scripts_are_valid_shell(self) -> None:
        fingerprint = "a" * 64
        download_url = "https://agent-vm.local:8443/infra-tools-ca.crt"
        scripts = (
            _linux_trust_script(
                fingerprint,
                download_url,
                "  sudo update-ca-certificates",
            ),
            _macos_trust_script(fingerprint, download_url),
        )

        for script in scripts:
            with self.subTest(script=script.splitlines()[-2]):
                result = subprocess.run(
                    ["/bin/bash", "-n"],
                    input=script,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(download_url, script)
                self.assertIn(fingerprint, script)
                self.assertLess(
                    script.index("actual_sha256"),
                    script.index("sudo "),
                )

    def test_page_renders_a_live_system_overview(self) -> None:
        state = WebPanelState(self._t3_manifest())
        overview = [
            {
                "label": "Memory",
                "value": "42% used",
                "description": "2.3 GiB available of 4.0 GiB",
            },
            {
                "label": "Maintenance",
                "value": "No reboot pending",
                "description": "Automatic package updates are scheduled",
            },
        ]
        with (
            patch(
                "common.service_tools.web_panel_service.discover_infra_web_services",
                return_value=[],
            ),
            patch.object(state, "system_overview", return_value=overview),
            patch(
                "common.service_tools.web_panel_service.os.path.isdir",
                return_value=True,
            ),
        ):
            rendered = render_page(state)

        self.assertIn("System overview", rendered)
        self.assertIn("42% used", rendered)
        self.assertIn("Automatic package updates are scheduled", rendered)

    def test_collects_bounded_system_overview_values(self) -> None:
        def open_file(path: str, **_kwargs: object) -> StringIO:
            if path == "/proc/uptime":
                return StringIO("183900.0 100.0\n")
            if path == "/proc/meminfo":
                return StringIO(
                    "MemTotal:       8388608 kB\n"
                    "MemAvailable:   4194304 kB\n"
                )
            raise FileNotFoundError(path)

        with (
            patch("builtins.open", side_effect=open_file),
            patch(
                "common.service_tools.web_panel_service.shutil.disk_usage",
                return_value=SimpleNamespace(
                    total=128 * 1024**3,
                    used=64 * 1024**3,
                    free=64 * 1024**3,
                ),
            ),
            patch(
                "common.service_tools.web_panel_service._timer_properties",
                return_value={
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "NextElapseUSecRealtime": "Tue 2026-09-01 06:00:00 CDT",
                },
            ),
            patch(
                "common.service_tools.web_panel_service.os.path.exists",
                return_value=False,
            ),
        ):
            overview = collect_system_overview()

        self.assertEqual(overview[0]["value"], "2d 3h")
        self.assertEqual(overview[1]["value"], "50% used")
        self.assertEqual(overview[2]["value"], "50% used")
        self.assertIn("Tue 2026-09-01", overview[3]["description"])

    def test_t3_update_uses_the_user_launcher_for_readiness(self) -> None:
        state = WebPanelState(self._t3_manifest())
        updated = SimpleNamespace(returncode=0, stdout="updated\n", stderr="")
        checked = SimpleNamespace(
            returncode=1,
            stdout=_t3_doctor_output(),
            stderr="",
        )

        @contextmanager
        def linger_shim(home: str, username: str):
            self.assertEqual(home, "/home/agent")
            self.assertEqual(username, "agent")
            yield "/home/agent/.infra-tools-t3-loginctl-test"

        with (
            patch(
                "common.service_tools.web_panel_service.os.path.expanduser",
                return_value="/home/agent",
            ),
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/home/agent/.local/bin/infra-tools",
            ) as mock_which,
            patch(
                "common.service_tools.web_panel_service.subprocess.run",
                side_effect=[updated, checked],
            ) as mock_run,
            patch(
                "common.service_tools.web_panel_service._temporary_t3_loginctl_shim",
                side_effect=linger_shim,
            ),
        ):
            state._run_t3_update()

        update_environment = mock_run.call_args_list[0].kwargs["env"]
        self.assertTrue(
            update_environment["PATH"].startswith(
                "/home/agent/.infra-tools-t3-loginctl-test:"
            )
        )
        self.assertEqual(
            update_environment["INFRA_TOOLS_T3_LOGINCTL_SHIM"],
            "/home/agent/.infra-tools-t3-loginctl-test",
        )
        self.assertIn(
            "$INFRA_TOOLS_T3_LOGINCTL_SHIM:",
            mock_run.call_args_list[0].args[0][2],
        )
        launcher_path = mock_run.call_args_list[1].kwargs["env"]["PATH"]
        self.assertTrue(launcher_path.startswith("/home/agent/.local/bin:"))
        self.assertNotIn(
            "INFRA_TOOLS_T3_LOGINCTL_SHIM",
            mock_run.call_args_list[1].kwargs["env"],
        )
        mock_which.assert_called_once_with("infra-tools", path=launcher_path)
        self.assertIn("--json", mock_run.call_args_list[1].args[0])
        self.assertEqual(state.action_status, "complete")
        self.assertIn("Not required by this setup", state.action_output)

    def test_t3_update_requires_github_checks_when_credentials_were_staged(self) -> None:
        manifest = self._t3_manifest()
        manifest["features"] = {
            "t3_update": True,
            "t3_github_readiness": True,
            "t3_git_identity_readiness": True,
        }
        state = WebPanelState(manifest)
        updated = SimpleNamespace(returncode=0, stdout="updated\n", stderr="")
        checked = SimpleNamespace(
            returncode=1,
            stdout=_t3_doctor_output(),
            stderr="",
        )
        with (
            patch(
                "common.service_tools.web_panel_service.subprocess.run",
                side_effect=[updated, checked],
            ),
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/home/agent/.local/bin/infra-tools",
            ),
            patch(
                "common.service_tools.web_panel_service._temporary_t3_loginctl_shim",
                return_value=nullcontext("/tmp/infra-tools-t3-loginctl-test"),
            ),
        ):
            state._run_t3_update()

        self.assertEqual(state.action_status, "failed")
        self.assertIn("GitHub CLI authenticated", state.action_output)

    def test_t3_update_still_requires_core_service_checks(self) -> None:
        state = WebPanelState(self._t3_manifest())
        updated = SimpleNamespace(returncode=0, stdout="updated\n", stderr="")
        checked = SimpleNamespace(
            returncode=1,
            stdout=_t3_doctor_output(endpoint=False),
            stderr="",
        )
        with (
            patch(
                "common.service_tools.web_panel_service.subprocess.run",
                side_effect=[updated, checked],
            ),
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value="/home/agent/.local/bin/infra-tools",
            ),
            patch(
                "common.service_tools.web_panel_service._temporary_t3_loginctl_shim",
                return_value=nullcontext("/tmp/infra-tools-t3-loginctl-test"),
            ),
        ):
            state._run_t3_update()

        self.assertEqual(state.action_status, "failed")
        self.assertIn("web endpoint responding", state.action_output)

    def test_t3_update_fails_closed_without_readiness_command(self) -> None:
        state = WebPanelState(self._t3_manifest())
        completed = SimpleNamespace(returncode=0, stdout="updated\n", stderr="")
        with (
            patch(
                "common.service_tools.web_panel_service.subprocess.run",
                return_value=completed,
            ),
            patch(
                "common.service_tools.web_panel_service.shutil.which",
                return_value=None,
            ),
            patch(
                "common.service_tools.web_panel_service._temporary_t3_loginctl_shim",
                return_value=nullcontext("/tmp/infra-tools-t3-loginctl-test"),
            ),
        ):
            state._run_t3_update()

        self.assertEqual(state.action_status, "failed")
        self.assertIn("readiness command is unavailable", state.action_message)

    def test_t3_update_guard_records_unexpected_failures(self) -> None:
        state = WebPanelState(self._t3_manifest())
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
