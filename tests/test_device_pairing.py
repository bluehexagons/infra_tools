"""Tests for protected, provider-native device enrollment."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

import remote_setup
from common.service_tools.device_pairing_service import (
    PairingError,
    PairingRequestHandler,
    PairingState,
    _safe_pairing_url,
)
from common.t3code_steps import (
    _configure_device_pairing,
    _configure_firewall,
    _write_passthrough_wrapper,
)
from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.cache import merge_setup_configs
from lib.interactive_setup import run_interactive_setup
from lib.setup_common import prepare_device_pairing_payload
from lib.validation import validate_web_interface_settings


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "agent-vm",
        "username": "agent",
        "system_type": "server_dev",
        "agent_tools": ["codex"],
        "web_interfaces": ["t3code"],
        "web_interface_sources": ["192.168.0.0/24"],
        "device_pairing_providers": ["t3code"],
    }
    values.update(overrides)
    return SetupConfig(**values)


class DevicePairingConfigTest(unittest.TestCase):
    def test_cli_and_config_preserve_policy_but_not_secret_source(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            [
                "agent-vm",
                "agent",
                "--agent-tool",
                "codex",
                "--web-interface",
                "t3code",
                "--web-interface-source",
                "192.168.0.0/24",
                "--device-pairing",
                "t3code",
                "--device-pairing-port",
                "4774",
                "--device-pairing-auth-file",
                "/run/secrets/pairing.htpasswd",
            ]
        )
        config = SetupConfig.from_args(args, "server_dev")
        validate_web_interface_settings(config)

        self.assertEqual(config.device_pairing_providers, ["t3code"])
        self.assertEqual(config.device_pairing_port, 4774)
        remote = " ".join(config.to_remote_args())
        saved = " ".join(config.to_setup_command())
        self.assertIn("--device-pairing t3code", remote)
        self.assertIn("--device-pairing-port 4774", remote)
        self.assertNotIn("pairing.htpasswd", remote)
        self.assertIn("--device-pairing t3code", saved)
        self.assertNotIn("pairing.htpasswd", saved)
        serialized = config.to_dict()
        self.assertNotIn("device_pairing_auth_file", serialized)
        self.assertNotIn("device_pairing_auth_password", serialized)

    def test_cli_password_defaults_portal_username_and_stays_transient(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            [
                "agent-vm",
                "agent",
                "--agent-tool",
                "codex",
                "--web-interface",
                "t3code",
                "--device-pairing",
                "t3code",
                "--device-pairing-password",
                "portal-secret",
            ]
        )
        config = SetupConfig.from_args(args, "server_dev")
        validate_web_interface_settings(config)

        self.assertEqual(config.device_pairing_auth_username, "agent")
        self.assertEqual(config.device_pairing_auth_password, "portal-secret")
        self.assertNotIn("portal-secret", " ".join(config.to_remote_args()))
        self.assertNotIn("portal-secret", " ".join(config.to_setup_command()))
        self.assertNotIn("portal-secret", str(config.to_dict()))

    def test_empty_cli_password_is_rejected(self) -> None:
        config = _config(device_pairing_auth_password="")
        with self.assertRaisesRegex(ValueError, "non-empty username and password"):
            validate_web_interface_settings(config)

    def test_provider_requires_matching_web_interface(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="server_dev",
            agent_tools=["codex"],
            device_pairing_providers=["t3code"],
        )
        with self.assertRaisesRegex(ValueError, "requires --web-interface"):
            validate_web_interface_settings(config)

    def test_pairing_port_must_differ_from_t3_port(self) -> None:
        with self.assertRaisesRegex(ValueError, "must differ"):
            _config(device_pairing_port=3773)

    def test_cli_does_not_silently_replace_invalid_zero_port(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            [
                "agent-vm",
                "agent",
                "--agent-tool",
                "codex",
                "--web-interface",
                "t3code",
                "--device-pairing",
                "t3code",
                "--device-pairing-port",
                "0",
            ]
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            SetupConfig.from_args(args, "server_dev")

    def test_auth_file_and_interactive_secret_are_mutually_exclusive(self) -> None:
        config = _config(
            device_pairing_auth_file="/tmp/auth",
            device_pairing_auth_username="agent",
            device_pairing_auth_password="secret",
        )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            validate_web_interface_settings(config)

    def test_explicit_disable_removes_cached_pairing_policy(self) -> None:
        cached = _config()
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["agent-vm", "agent", "--no-device-pairing"])
        update = SetupConfig.from_args(args, "server_dev")

        merged = merge_setup_configs(cached, update)

        self.assertIsNone(merged.device_pairing_providers)
        self.assertTrue(merged.disable_device_pairing)

    def test_interactive_prompts_for_auth_when_provider_was_explicit(self) -> None:
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            [
                "agent-vm",
                "agent",
                "--agent-tool",
                "codex",
                "--web-interface",
                "t3code",
                "--web-interface-source",
                "192.168.0.0/24",
                "--device-pairing",
                "t3code",
                "--interactive",
            ]
        )
        responses = ["", "none", "none", "no", "pair-admin"]
        with (
            patch("lib.interactive_setup.sys.stdin.isatty", return_value=True),
            patch("lib.interactive_setup.sys.stdout.isatty", return_value=True),
            patch("builtins.input", side_effect=responses),
            patch(
                "lib.interactive_setup.getpass.getpass",
                side_effect=["portal-secret", "portal-secret"],
            ),
        ):
            run_interactive_setup(args)

        self.assertEqual(args.device_pairing_auth_username, "pair-admin")
        self.assertEqual(args.device_pairing_auth_password, "portal-secret")


class DevicePairingPayloadTest(unittest.TestCase):
    def test_stages_valid_hashed_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = os.path.join(temporary, "source.htpasswd")
            destination = os.path.join(temporary, "payload")
            with open(source, "w", encoding="utf-8") as file_obj:
                file_obj.write("agent:$6$salt$hash\n")
            os.chmod(source, 0o600)
            config = _config(device_pairing_auth_file=source)

            prepare_device_pairing_payload(config, destination)

            staged = os.path.join(destination, "htpasswd")
            with open(staged, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "agent:$6$salt$hash\n")
            self.assertEqual(os.stat(staged).st_mode & 0o777, 0o600)

    def test_rejects_plaintext_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = os.path.join(temporary, "source.htpasswd")
            with open(source, "w", encoding="utf-8") as file_obj:
                file_obj.write("agent:plaintext\n")
            os.chmod(source, 0o600)
            config = _config(device_pairing_auth_file=source)
            with self.assertRaisesRegex(ValueError, "must use crypt"):
                prepare_device_pairing_payload(
                    config, os.path.join(temporary, "payload")
                )

    def test_rejects_unsalted_sha_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = os.path.join(temporary, "source.htpasswd")
            with open(source, "w", encoding="utf-8") as file_obj:
                file_obj.write("agent:{SHA}qvTGHdzF6KLavt4PO0gs2a6pQ00=\n")
            os.chmod(source, 0o600)
            config = _config(device_pairing_auth_file=source)
            with self.assertRaisesRegex(ValueError, "crypt-style"):
                prepare_device_pairing_payload(
                    config, os.path.join(temporary, "payload")
                )

    def test_generates_sha512_crypt_hash_without_putting_password_in_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(
                device_pairing_auth_username="agent",
                device_pairing_auth_password="very-secret",
            )
            completed = SimpleNamespace(returncode=0, stdout="$6$salt$hash\n")
            with patch("lib.setup_common.subprocess.run", return_value=completed) as mock_run:
                prepare_device_pairing_payload(config, temporary)

            self.assertEqual(mock_run.call_args.args[0], ["openssl", "passwd", "-6", "-stdin"])
            self.assertEqual(mock_run.call_args.kwargs["input"], "very-secret\n")
            self.assertNotIn("very-secret", mock_run.call_args.args[0])

    def test_password_only_uses_target_username_for_htpasswd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(device_pairing_auth_password="very-secret")
            completed = SimpleNamespace(returncode=0, stdout="$6$salt$hash\n")
            with patch("lib.setup_common.subprocess.run", return_value=completed):
                prepare_device_pairing_payload(config, temporary)

            with open(
                os.path.join(temporary, "htpasswd"), encoding="utf-8"
            ) as file_obj:
                self.assertEqual(file_obj.read(), "agent:$6$salt$hash\n")

    def test_remote_cleanup_removes_all_uploaded_secret_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            agent_payload = os.path.join(temporary, "agent")
            pairing_payload = os.path.join(temporary, "pairing")
            os.makedirs(agent_payload)
            os.makedirs(pairing_payload)
            with (
                patch.object(
                    remote_setup, "REMOTE_AGENT_PAYLOAD_DIR", agent_payload
                ),
                patch.object(
                    remote_setup,
                    "REMOTE_DEVICE_PAIRING_PAYLOAD_DIR",
                    pairing_payload,
                ),
                patch.object(remote_setup, "is_dry_run", return_value=False),
            ):
                remote_setup._remove_secret_payloads()

            self.assertFalse(os.path.exists(agent_payload))
            self.assertFalse(os.path.exists(pairing_payload))


class PairingBrokerTest(unittest.TestCase):
    def _provider(self) -> dict[str, object]:
        return {
            "label": "T3 Code",
            "command": ["/opt/t3", "auth", "pairing", "create", "--json"],
            "base_url_flag": "--base-url",
            "url_field": "pairUrl",
            "expires_field": "expiresAt",
            "public_port": 3773,
        }

    def test_issues_provider_link_with_public_base_url_as_argv(self) -> None:
        state = PairingState({"t3code": self._provider()})
        output = json.dumps(
            {
                "pairUrl": "http://192.168.0.41:3773/pair#token=ONETIME",
                "expiresAt": "2026-08-20T18:00:00Z",
            }
        )
        completed = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch(
            "common.service_tools.device_pairing_service.subprocess.run",
            return_value=completed,
        ) as mock_run:
            pair_url, expires = state.issue(
                "t3code", "http://192.168.0.41:3773"
            )

        command = mock_run.call_args.args[0]
        self.assertEqual(command[-2:], ["--base-url", "http://192.168.0.41:3773"])
        self.assertEqual(pair_url, "http://192.168.0.41:3773/pair#token=ONETIME")
        self.assertEqual(expires, "2026-08-20T18:00:00Z")

    def test_rejects_provider_redirect_to_another_origin(self) -> None:
        with self.assertRaises(PairingError):
            _safe_pairing_url(
                "https://attacker.example/pair#token=secret",
                "http://192.168.0.41:3773",
            )

    def test_rejects_control_characters_in_provider_url(self) -> None:
        with self.assertRaises(PairingError):
            _safe_pairing_url(
                "http://192.168.0.41:3773/pair#token=secret\r\nX-Bad: yes",
                "http://192.168.0.41:3773",
            )

    def test_nonce_is_single_use(self) -> None:
        state = PairingState({"t3code": self._provider()})
        nonce = state.new_nonce()
        self.assertTrue(state.consume_nonce(nonce))
        self.assertFalse(state.consume_nonce(nonce))

    def test_pairing_issuance_is_rate_limited_per_source(self) -> None:
        state = PairingState({"t3code": self._provider()})
        for _index in range(5):
            self.assertTrue(state.allow_request("192.168.0.12"))
        self.assertFalse(state.allow_request("192.168.0.12"))
        self.assertTrue(state.allow_request("192.168.0.13"))

    def test_http_portal_renders_explicit_single_use_provider_link(self) -> None:
        state = PairingState({"t3code": self._provider()})
        nonce = state.new_nonce()
        body = urlencode({"nonce": nonce, "intent": "current"}).encode("utf-8")
        headers = Message()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(body))
        headers["Cookie"] = f"infra_tools_pairing_nonce={nonce}"
        headers["X-Forwarded-Host"] = "agent-vm"
        headers["X-Forwarded-Proto"] = "http"
        headers["X-Real-IP"] = "192.168.0.12"
        handler = PairingRequestHandler.__new__(PairingRequestHandler)
        handler.server = SimpleNamespace(pairing_state=state)
        handler.path = "/pair/t3code"
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /pair/t3code HTTP/1.1"
        handler.headers = headers
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        pairing_url = "http://agent-vm:3773/pair#token=ONETIME"

        with patch.object(
            state,
            "issue",
            return_value=(pairing_url, "2026-08-20T18:00:00Z"),
        ) as issue:
            handler.do_POST()

        response = handler.wfile.getvalue().decode("iso-8859-1")
        self.assertIn(" 200 ", response)
        self.assertNotIn("Location:", response)
        self.assertIn(f'href="{pairing_url}"', response)
        self.assertIn("Pair this browser with T3 Code", response)
        issue.assert_called_once_with("t3code", "http://agent-vm:3773")

    def test_http_portal_rejects_missing_pairing_intent(self) -> None:
        state = PairingState({"t3code": self._provider()})
        nonce = state.new_nonce()
        body = urlencode({"nonce": nonce}).encode("utf-8")
        headers = Message()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(body))
        headers["Cookie"] = f"infra_tools_pairing_nonce={nonce}"
        handler = PairingRequestHandler.__new__(PairingRequestHandler)
        handler.server = SimpleNamespace(pairing_state=state)
        handler.path = "/pair/t3code"
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /pair/t3code HTTP/1.1"
        handler.headers = headers
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()

        with patch.object(state, "issue") as issue:
            handler.do_POST()

        response = handler.wfile.getvalue().decode("iso-8859-1")
        self.assertIn(" 403 ", response)
        issue.assert_not_called()


class DevicePairingRemoteSetupTest(unittest.TestCase):
    def test_provider_wrapper_refuses_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            victim = os.path.join(temporary, "victim")
            wrapper = os.path.join(temporary, "wrapper")
            with open(victim, "w", encoding="utf-8") as file_obj:
                file_obj.write("unchanged")
            os.symlink(victim, wrapper)

            with self.assertRaisesRegex(RuntimeError, "unsafe managed executable"):
                _write_passthrough_wrapper(wrapper, temporary, "/opt/t3")

            with open(victim, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "unchanged")

    def test_writes_basic_auth_nginx_and_native_t3_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config()
            config_dir = os.path.join(temporary, "config")
            payload_dir = os.path.join(temporary, "payload")
            nginx_available = os.path.join(temporary, "nginx-available")
            nginx_enabled = os.path.join(temporary, "nginx-enabled")
            os.makedirs(payload_dir)
            with open(os.path.join(payload_dir, "htpasswd"), "w", encoding="utf-8") as file_obj:
                file_obj.write("agent:$6$salt$hash\n")
            account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

            constants = {
                "DEVICE_PAIRING_CONFIG_DIR": config_dir,
                "DEVICE_PAIRING_AUTH_FILE": os.path.join(config_dir, "htpasswd"),
                "DEVICE_PAIRING_PROVIDERS_FILE": os.path.join(
                    config_dir, "providers.json"
                ),
                "DEVICE_PAIRING_PAYLOAD_FILE": os.path.join(payload_dir, "htpasswd"),
                "DEVICE_PAIRING_SERVICE_FILE": os.path.join(temporary, "pairing.service"),
                "DEVICE_PAIRING_NGINX_SITE": nginx_available,
                "DEVICE_PAIRING_NGINX_LINK": nginx_enabled,
                "DEVICE_PAIRING_SOCKET": "/run/infra-tools-device-pairing/http.sock",
                "DEVICE_PAIRING_SCRIPT": "/opt/infra_tools/common/service_tools/device_pairing_service.py",
            }

            def run_command(_command: str, **_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.multiple("common.t3code_steps", **constants),
                patch("common.t3code_steps.pwd.getpwnam", return_value=account),
                patch("common.t3code_steps.os.chown"),
                patch("common.t3code_steps.run", side_effect=run_command),
                patch("web.web_steps.install_nginx"),
            ):
                _configure_device_pairing(
                    config,
                    temporary,
                    "/home/agent/.local/share/infra-tools/t3code/node_modules/.bin/t3",
                    "0.0.0.0",
                    3773,
                )

            with open(nginx_available, encoding="utf-8") as file_obj:
                nginx = file_obj.read()
            self.assertIn('auth_basic "Device pairing"', nginx)
            self.assertIn("listen 0.0.0.0:3774", nginx)
            self.assertIn(
                "proxy_pass http://unix:"
                "/run/infra-tools-device-pairing/http.sock:/",
                nginx,
            )
            with open(
                os.path.join(config_dir, "providers.json"), encoding="utf-8"
            ) as file_obj:
                providers = json.load(file_obj)
            command = providers["providers"]["t3code"]["command"]
            self.assertIn("pairing", command)
            self.assertIn("create", command)
            self.assertNotIn("--port", command)
            self.assertIn("--json", command)
            self.assertNotIn("$6$salt$hash", json.dumps(providers))
            provider_wrapper = command[0]
            with open(provider_wrapper, encoding="utf-8") as file_obj:
                wrapper = file_obj.read()
            self.assertIn('export NVM_DIR="$HOME/.nvm"', wrapper)
            self.assertIn('"$@"', wrapper)
            with open(
                os.path.join(temporary, "pairing.service"), encoding="utf-8"
            ) as file_obj:
                service = file_obj.read()
            self.assertIn("Environment=T3CODE_PORT=3773", service)

    def test_firewall_includes_pairing_port(self) -> None:
        config = _config()
        comments: list[str] = []

        def run_command(command: str, **_kwargs: object) -> SimpleNamespace:
            if command == "ufw status numbered":
                lines = [
                    f"[ {index}] {3772 + index}/tcp ALLOW IN 192.168.0.0/24 # {comment}"
                    for index, comment in enumerate(comments, 1)
                ]
                return SimpleNamespace(returncode=0, stdout="\n".join(lines))
            if command.startswith("ufw allow from"):
                marker = command.split(" comment ", 1)[1].strip("'")
                comments.append(marker)
            return SimpleNamespace(returncode=0, stdout="")

        with patch("common.t3code_steps.run", side_effect=run_command):
            _configure_firewall(config, 3773, "0.0.0.0")

        self.assertTrue(any("3773/tcp" in comment for comment in comments))
        self.assertTrue(any("pairing 3774/tcp" in comment for comment in comments))


if __name__ == "__main__":
    unittest.main()
