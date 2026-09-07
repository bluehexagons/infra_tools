"""Godot manifest, staged payload and generated Nginx contract tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lib.deployment import DeploymentOrchestrator
from lib.godot_deploy import validate_godot_export
from lib.nginx_config import generate_merged_nginx_config
from lib.project_manifest import Manifest, parse_manifest


def manifest(**overrides):
    component = dict(name="player", type="godot-web", domain="example.com",
                     path="/music", output="exports/web")
    component.update(overrides)
    return parse_manifest(dict(version=1, components=[component]))


class GodotDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "exports/web"
        self.output.mkdir(parents=True)
        for name, data in {"index.html": b"<!doctype html>", "index.js": b"// engine",
                           "index.wasm": b"\x00asm\x01\x00\x00\x00", "index.pck": b"GDPC"}.items():
            (self.output / name).write_bytes(data)

    def test_valid_export_and_descriptor(self):
        model = manifest()
        DeploymentOrchestrator._validate_manifest_artifacts(model, str(self.root))
        dep = DeploymentOrchestrator()._component_dep(model.components[0], str(self.root))
        self.assertEqual(dep["project_type"], "godot-web")
        self.assertFalse(dep["needs_proxy"])
        self.assertEqual(dep["serve_path"], str(self.output))

    def test_rejects_incomplete_or_nonbinary_export(self):
        for name in ("index.html", "index.js", "index.wasm", "index.pck"):
            with self.subTest(name=name):
                original = (self.output / name).read_bytes()
                (self.output / name).write_bytes(b"")
                with self.assertRaises(RuntimeError):
                    DeploymentOrchestrator._validate_manifest_artifacts(manifest(), str(self.root))
                (self.output / name).write_bytes(original)
        (self.output / "index.wasm").write_text("HTML error page")
        with self.assertRaisesRegex(RuntimeError, "WebAssembly"):
            validate_godot_export(str(self.output), str(self.root))

    def test_rejects_symlinks_and_escaping_output(self):
        (self.output / "link").symlink_to(self.output / "index.html")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            validate_godot_export(str(self.output), str(self.root))
        (self.output / "link").unlink()
        (self.root / "alias").symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            validate_godot_export(str(self.root / "alias"), str(self.root))
        with self.assertRaisesRegex(RuntimeError, "escapes"):
            validate_godot_export(str(self.root), str(self.output))

    def test_export_limits(self):
        with patch("lib.godot_deploy.MAX_FILES", 2), self.assertRaisesRegex(RuntimeError, "limits"):
            validate_godot_export(str(self.output), str(self.root))
        with patch("lib.godot_deploy.MAX_BYTES", 2), self.assertRaisesRegex(RuntimeError, "limits"):
            validate_godot_export(str(self.output), str(self.root))

    def test_safe_manifest_paths(self):
        for kwargs in ({"path": "/a;"}, {"path": "/../a"}, {"output": "../secret"},
                       {"output": "x y"}, {"binary": "app"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                manifest(**kwargs)
        self.assertTrue(manifest(output=".").components[0].is_static)

    def test_nginx_root_and_subpath(self):
        for route in ("/", "/music", "/music/"):
            dep = DeploymentOrchestrator()._component_dep(manifest(path=route).components[0], "/var/www/game")
            config = generate_merged_nginx_config("example.com", [dep])
            self.assertIn('Cross-Origin-Opener-Policy "same-origin" always', config)
            self.assertIn('Cross-Origin-Embedder-Policy "require-corp" always', config)
            self.assertIn('Cache-Control "no-cache" always', config)
            self.assertIn("application/wasm wasm;", config)
            self.assertIn("application/javascript js;", config)
            self.assertIn("disable_symlinks on;", config)
            self.assertNotIn("try_files", config)
            if route == "/":
                self.assertIn("root /var/www/game/exports/web/;", config)
            else:
                self.assertIn("location = /music", config)
                self.assertIn("return 301 /music/;", config)
                self.assertIn("alias /var/www/game/exports/web/;", config)

    def test_trailing_slash_route_collision(self):
        model = Manifest(version=1, components=[manifest(path="/music").components[0],
            manifest(name="other", type="static", path="/music/").components[0]])
        with self.assertRaisesRegex(RuntimeError, "both declare"):
            DeploymentOrchestrator()._validate_manifest_routes(model, None)

    def test_failed_export_preserves_active_release(self):
        with tempfile.TemporaryDirectory() as destination:
            orch = DeploymentOrchestrator(base_dir=destination)
            url = "https://example.com/game.git"
            live = Path(orch.get_deployment_path("example.com", "/", url))
            live.mkdir()
            (live / "index.html").write_text("previous release")
            (self.output / "index.pck").unlink()
            with patch("lib.deployment.run", return_value=MagicMock(returncode=0)), \
                    patch.object(orch, "_ensure_build_user"), \
                    patch.object(orch, "_prepare_build_toolchain"), \
                    patch.object(orch, "_run_component_build"), \
                    patch.object(orch, "_app_unit_snapshots", return_value={}), \
                    patch.object(orch, "_stop_app_unit") as stop:
                with self.assertRaisesRegex(RuntimeError, "index.pck"):
                    orch.deploy_manifest(manifest(), str(self.root), "example.com", "/", url, "abc")
                stop.assert_not_called()
            self.assertEqual((live / "index.html").read_text(), "previous release")


if __name__ == "__main__":
    unittest.main()
