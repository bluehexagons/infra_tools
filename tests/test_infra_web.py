"""Tests for the target-side managed HTTPS gateway utility."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.service_tools import infra_web


def _policy() -> dict[str, object]:
    return {
        "access_sources": ["192.0.2.0/24"],
        "base_url": "https://games.example:8443",
        "ca_certificate": "/var/lib/infra_tools/internal-web-pki/ca.crt",
        "certificate": "/certs/server.crt",
        "certificate_key": "/certs/server.key",
        "forward_port_max": 8499,
        "forward_port_min": 8444,
        "users": ["agent"],
        "version": 1,
    }


class TestInfraWebForwarding(unittest.TestCase):
    def test_rejects_non_loopback_upstream(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            infra_web._parse_upstream("192.0.2.10:3000")

    def test_renders_tls_websocket_forward_with_godot_headers(self) -> None:
        route = {
            "listen": 8444,
            "name": "preview",
            "owner": "agent",
            "profile": "godot",
            "target_host": "127.0.0.1",
            "target_port": 3000,
        }

        content = infra_web.render_forward_nginx([route], _policy())

        self.assertIn("listen 8444 ssl", content)
        self.assertIn("proxy_pass http://127.0.0.1:3000", content)
        self.assertIn("proxy_set_header Upgrade $http_upgrade", content)
        self.assertIn("Cross-Origin-Opener-Policy \"same-origin\"", content)
        self.assertIn("Cross-Origin-Embedder-Policy \"require-corp\"", content)

    def test_forward_add_uses_policy_owner_and_atomic_apply(self) -> None:
        with (
            patch.object(infra_web, "_load_policy", return_value=_policy()),
            patch.object(infra_web, "_load_forwards", return_value=[]),
            patch.object(infra_web, "_requesting_username", return_value="agent"),
            patch.object(infra_web, "_select_listen_port", return_value=8444),
            patch.object(infra_web, "_apply_forwards") as apply_forwards,
        ):
            result = infra_web.main(
                [
                    "forward",
                    "add",
                    "preview",
                    "--to",
                    "127.0.0.1:3000",
                    "--profile",
                    "godot",
                    "--json",
                ]
            )

        self.assertEqual(result, 0)
        routes = apply_forwards.call_args.args[0]
        self.assertEqual(
            routes,
            [
                {
                    "listen": 8444,
                    "name": "preview",
                    "owner": "agent",
                    "profile": "godot",
                    "target_host": "127.0.0.1",
                    "target_port": 3000,
                }
            ],
        )

    def test_policy_loader_validates_forwarding_range_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            policy_path = os.path.join(temporary_dir, "policy.json")
            with open(policy_path, "w", encoding="utf-8") as file_obj:
                json.dump(_policy(), file_obj)
            with patch.object(infra_web, "POLICY_FILE", policy_path):
                loaded = infra_web._load_policy()

        self.assertEqual(loaded["access_sources"], ["192.0.2.0/24"])
        self.assertEqual(loaded["forward_port_min"], 8444)

    def test_firewall_port_match_does_not_match_larger_port(self) -> None:
        line = "[ 1] 18444/tcp ALLOW IN Anywhere"

        self.assertFalse(infra_web._ufw_rule_matches_port(line, 8444))
        self.assertTrue(infra_web._ufw_rule_matches_port(line, 18444))


class TestInfraWebGames(unittest.TestCase):
    def test_remove_deletes_only_confirmed_owned_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            games_root = os.path.join(temporary_dir, "games")
            user_root = os.path.join(games_root, "agent")
            game_root = os.path.join(user_root, "demo")
            os.makedirs(game_root)
            with open(os.path.join(game_root, "index.html"), "w", encoding="utf-8"):
                pass
            account = SimpleNamespace(pw_uid=os.getuid(), pw_name="agent")
            with (
                patch.object(infra_web, "GAMES_ROOT", games_root),
                patch.object(infra_web.godot_web_publish, "GAMES_ROOT", games_root),
                patch.object(infra_web, "_game_account", return_value=account),
                patch.object(
                    infra_web.godot_web_publish,
                    "BASE_URL_FILE",
                    os.path.join(temporary_dir, "base-url"),
                ),
            ):
                result = infra_web.main(["remove", "demo", "--yes"])

            self.assertEqual(result, 0)
            self.assertFalse(os.path.exists(game_root))
            self.assertTrue(os.path.isfile(os.path.join(user_root, "index.html")))

    def test_doctor_requires_godot_headers_and_wasm_mime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            games_root = os.path.join(temporary_dir, "games")
            game_root = os.path.join(games_root, "agent", "demo")
            os.makedirs(game_root)
            with open(os.path.join(game_root, "index.html"), "w", encoding="utf-8"):
                pass
            with open(os.path.join(game_root, "demo.wasm"), "w", encoding="utf-8"):
                pass
            account = SimpleNamespace(pw_uid=os.getuid(), pw_name="agent")
            response_headers = [
                (
                    200,
                    {
                        "cross-origin-opener-policy": "same-origin",
                        "cross-origin-embedder-policy": "require-corp",
                    },
                ),
                (206, {"content-type": "application/wasm"}),
            ]
            with (
                patch.object(infra_web, "GAMES_ROOT", games_root),
                patch.object(infra_web, "_game_account", return_value=account),
                patch.object(
                    infra_web.godot_web_publish,
                    "BASE_URL_FILE",
                    os.path.join(temporary_dir, "base-url"),
                ),
                patch.object(
                    infra_web.godot_web_publish,
                    "_published_url",
                    return_value="https://games.example:8443/games/agent/demo/",
                ),
                patch.object(infra_web, "_https_headers", side_effect=response_headers),
            ):
                result = infra_web.main(["doctor", "demo", "--json"])

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
