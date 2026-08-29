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

    def test_renders_validated_per_route_request_body_limit(self) -> None:
        route = {
            "listen": 8444,
            "max_body_size": "50m",
            "name": "t3code",
            "owner": "agent",
            "profile": "general",
            "target_host": "127.0.0.1",
            "target_port": 3773,
        }

        content = infra_web.render_forward_nginx([route], _policy())

        self.assertIn("client_max_body_size 50m;", content)

    def test_rejects_unsafe_or_unbounded_request_body_limit(self) -> None:
        for value in ("0", "2g", "50m; include /tmp/unsafe"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    infra_web._validate_body_size(value, "--max-body-size")

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
                    "--max-body-size",
                    "50M",
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
                    "max_body_size": "50m",
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

    def test_forward_waits_for_http_readiness_before_apply(self) -> None:
        with (
            patch.object(infra_web, "_load_policy", return_value=_policy()),
            patch.object(infra_web, "_load_forwards", return_value=[]),
            patch.object(infra_web, "_requesting_username", return_value="agent"),
            patch.object(infra_web, "_select_listen_port", return_value=8444),
            patch.object(infra_web, "_wait_for_upstream") as wait,
            patch.object(infra_web, "_apply_forwards"),
        ):
            result = infra_web.main(
                [
                    "forward",
                    "add",
                    "preview",
                    "--to",
                    "127.0.0.1:3000",
                    "--wait",
                    "10",
                    "--health",
                    "/ready",
                ]
            )

        self.assertEqual(result, 0)
        wait.assert_called_once_with("127.0.0.1", 3000, "/ready", 10.0)

    def test_forward_prune_preserves_managed_preview_routes(self) -> None:
        route = {
            "listen": 8444,
            "name": "preview",
            "owner": "agent",
            "profile": "general",
            "target_host": "127.0.0.1",
            "target_port": 4173,
        }
        preview = {
            "name": "preview",
            "owner": "agent",
        }
        with (
            patch.object(infra_web, "_load_policy", return_value=_policy()),
            patch.object(infra_web, "_load_forwards", return_value=[route]),
            patch.object(infra_web, "_load_previews", return_value=[preview]),
            patch.object(infra_web, "_requesting_username", return_value="agent"),
            patch.object(infra_web, "_tcp_ready", return_value=False),
            patch.object(infra_web, "_apply_forwards") as apply_forwards,
        ):
            result = infra_web.main(["forward", "prune", "--yes", "--json"])

        self.assertEqual(result, 0)
        apply_forwards.assert_not_called()

    def test_doctor_accepts_authenticated_forward_challenge(self) -> None:
        route = {
            "listen": 8444,
            "name": "protected",
            "owner": "agent",
            "profile": "general",
            "target_host": "127.0.0.1",
            "target_port": 3000,
        }
        account = SimpleNamespace(pw_name="agent")
        with tempfile.TemporaryDirectory() as games_root:
            with (
                patch.object(infra_web, "_game_account", return_value=account),
                patch.object(infra_web, "_user_root", return_value=games_root),
                patch.object(infra_web, "_load_policy", return_value=_policy()),
                patch.object(infra_web, "_load_forwards", return_value=[route]),
                patch.object(
                    infra_web,
                    "_https_headers",
                    return_value=(401, {"www-authenticate": 'Basic realm="Protected"'}),
                ),
                patch("builtins.print"),
            ):
                result = infra_web.main(["doctor", "protected", "--json"])

        self.assertEqual(result, 0)

    def test_doctor_rejects_unauthorized_forward_without_challenge(self) -> None:
        route = {
            "listen": 8444,
            "name": "broken",
            "owner": "agent",
            "profile": "general",
            "target_host": "127.0.0.1",
            "target_port": 3000,
        }
        account = SimpleNamespace(pw_name="agent")
        with tempfile.TemporaryDirectory() as games_root:
            with (
                patch.object(infra_web, "_game_account", return_value=account),
                patch.object(infra_web, "_user_root", return_value=games_root),
                patch.object(infra_web, "_load_policy", return_value=_policy()),
                patch.object(infra_web, "_load_forwards", return_value=[route]),
                patch.object(infra_web, "_https_headers", return_value=(401, {})),
                patch("builtins.print"),
            ):
                result = infra_web.main(["doctor", "broken", "--json"])

        self.assertEqual(result, 1)


class TestInfraWebPreviews(unittest.TestCase):
    def test_automatic_vite_command_is_loopback_only_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            with open(os.path.join(project, "package.json"), "w", encoding="utf-8") as file_obj:
                json.dump(
                    {
                        "scripts": {"dev": "vite"},
                        "devDependencies": {"vite": "1.0.0"},
                    },
                    file_obj,
                )

            command = infra_web._automatic_preview_command(project, 4173)

        self.assertEqual(command[:3], ["npm", "run", "dev"])
        self.assertIn("127.0.0.1", command)
        self.assertIn("4173", command)
        self.assertIn("--strictPort", command)

    def test_relative_preview_executable_is_resolved_from_project(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            executable = os.path.join(project, "serve-preview")
            with open(executable, "w", encoding="utf-8") as file_obj:
                file_obj.write("#!/bin/sh\n")
            os.chmod(executable, 0o755)
            account = SimpleNamespace(pw_dir="/home/agent")

            command = infra_web._resolve_preview_executable(
                ["./serve-preview", "--port", "4173"],
                account,
                project,
            )

        self.assertEqual(command[0], executable)
        self.assertEqual(command[1:], ["--port", "4173"])

    def test_rendered_preview_unit_runs_as_owner_with_resource_bounds(self) -> None:
        account = SimpleNamespace(
            pw_dir="/home/agent",
            pw_gid=os.getgid(),
            pw_name="agent",
        )
        group = SimpleNamespace(gr_name="agent")
        with patch.object(infra_web.grp, "getgrgid", return_value=group):
            content = infra_web.render_preview_unit(
                "demo",
                account,
                "/home/agent/repos/demo",
                "/var/lib/infra_tools/internal-web-previews/agent-demo.sh",
            )

        self.assertIn("User=agent", content)
        self.assertIn("Group=agent", content)
        self.assertIn("NoNewPrivileges=true", content)
        self.assertIn("MemoryMax=1G", content)
        self.assertNotIn("WantedBy=", content)

    def test_missing_preview_dependencies_install_as_requesting_user(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            with open(os.path.join(project, "package-lock.json"), "w", encoding="utf-8"):
                pass
            account = SimpleNamespace(pw_dir="/home/agent", pw_name="agent")
            completed = SimpleNamespace(returncode=0)
            with (
                patch.object(
                    infra_web,
                    "_resolve_preview_executable",
                    return_value=["/home/agent/.nvm/current/bin/npm", "ci"],
                ),
                patch.object(infra_web.subprocess, "run", return_value=completed) as run,
            ):
                infra_web._install_preview_dependencies(project, account)

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["runuser", "-u", "agent", "--"])
        self.assertIn("HOME=/home/agent", command)
        self.assertEqual(command[-2:], ["/home/agent/.nvm/current/bin/npm", "ci"])

    def test_preview_start_waits_then_applies_route_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            account = SimpleNamespace(
                pw_dir=os.path.dirname(project),
                pw_gid=os.getgid(),
                pw_name="agent",
                pw_uid=os.getuid(),
            )
            with (
                patch.object(infra_web.os, "geteuid", return_value=0),
                patch.object(infra_web, "_load_policy", return_value=_policy()),
                patch.object(infra_web, "_requesting_username", return_value="agent"),
                patch.object(infra_web.pwd, "getpwnam", return_value=account),
                patch.object(infra_web, "_load_forwards", return_value=[]),
                patch.object(infra_web, "_load_previews", return_value=[]),
                patch.object(infra_web, "_select_target_port", return_value=4173),
                patch.object(infra_web, "_select_listen_port", return_value=8444),
                patch.object(
                    infra_web,
                    "_resolve_preview_executable",
                    return_value=["/usr/bin/true", "4173"],
                ),
                patch.object(
                    infra_web,
                    "_write_preview_service",
                    return_value=("infra-web-preview-agent-demo.service", "/launcher"),
                ),
                patch.object(infra_web, "_wait_for_upstream") as wait,
                patch.object(infra_web, "_apply_forwards") as apply_forwards,
                patch.object(infra_web, "_write_preview_state") as write_state,
            ):
                result = infra_web.main(
                    [
                        "preview",
                        "start",
                        "demo",
                        "--project",
                        project,
                        "--json",
                        "--",
                        "/usr/bin/true",
                        "{port}",
                    ]
                )

        self.assertEqual(result, 0)
        wait.assert_called_once_with("127.0.0.1", 4173, "/", 30)
        routes = apply_forwards.call_args.args[0]
        self.assertEqual(routes[0]["target_port"], 4173)
        self.assertEqual(routes[0]["listen"], 8444)
        state = write_state.call_args.args[0]
        self.assertEqual(state[0]["unit"], "infra-web-preview-agent-demo.service")
        self.assertNotIn("command", state[0])

    def test_preview_stop_removes_route_service_and_state(self) -> None:
        record = {
            "created_at": "2026-01-01T00:00:00Z",
            "health": "/",
            "listen": 8444,
            "name": "demo",
            "owner": "agent",
            "profile": "general",
            "project": "/home/agent/demo",
            "target_host": "127.0.0.1",
            "target_port": 4173,
            "unit": "infra-web-preview-agent-demo.service",
        }
        route = {
            "listen": 8444,
            "name": "demo",
            "owner": "agent",
            "profile": "general",
            "target_host": "127.0.0.1",
            "target_port": 4173,
        }
        with (
            patch.object(infra_web.os, "geteuid", return_value=0),
            patch.object(infra_web, "_load_policy", return_value=_policy()),
            patch.object(infra_web, "_requesting_username", return_value="agent"),
            patch.object(infra_web, "_load_forwards", return_value=[route]),
            patch.object(infra_web, "_load_previews", return_value=[record]),
            patch.object(infra_web, "_apply_forwards") as apply_forwards,
            patch.object(infra_web, "_remove_preview_service") as remove_service,
            patch.object(infra_web, "_write_preview_state") as write_state,
        ):
            result = infra_web.main(["preview", "stop", "demo", "--json"])

        self.assertEqual(result, 0)
        apply_forwards.assert_called_once_with([], _policy())
        remove_service.assert_called_once_with(record)
        write_state.assert_called_once_with([])


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
