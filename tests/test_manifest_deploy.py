"""Tests for infra.json manifest deployment wiring (phase 2).

Covers the systemd unit generator, component -> nginx descriptor mapping, the
DeploymentOrchestrator.deploy_manifest flow (with run/service/health mocked),
and that the generated descriptors drive correct nginx config.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.deployment import DeploymentOrchestrator
from lib.nginx_config import generate_merged_nginx_config
from lib.project_manifest import Component, Manifest, parse_manifest
from lib.systemd_service import generate_managed_service


def _static_component(**overrides: object) -> Component:
    data = {
        "name": "site",
        "type": "static",
        "domain": "example.com",
        "build": "npm ci && npm run build",
        "output": "dist",
    }
    data.update(overrides)
    return parse_manifest({"version": 1, "components": [data]}).components[0]


def _service_component(**overrides: object) -> Component:
    data = {
        "name": "api",
        "type": "service",
        "domain": "api.example.com",
        "build": "server/build.sh",
        "binary": "server/app",
        "port": 8090,
    }
    data.update(overrides)
    return parse_manifest({"version": 1, "components": [data]}).components[0]


class TestGenerateManagedService(unittest.TestCase):
    def test_includes_exec_and_hardening(self):
        unit = generate_managed_service(
            "app-api", "/var/www/site/server/app", "/var/www/site",
            web_user="app-site-api", web_group="app-site-api",
        )
        self.assertIn("ExecStart=/var/www/site/server/app", unit)
        self.assertIn("WorkingDirectory=/var/www/site", unit)
        self.assertIn("User=app-site-api", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=full", unit)
        self.assertIn("[Install]", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_env_file_optional(self):
        without = generate_managed_service("app-api", "/bin/app", "/srv")
        self.assertNotIn("EnvironmentFile=", without)

        with_env = generate_managed_service(
            "app-api", "/bin/app", "/srv", env_file="/opt/app/.env"
        )
        self.assertIn("EnvironmentFile=/opt/app/.env", with_env)

    def test_runtime_environment_is_written_and_escaped(self):
        unit = generate_managed_service(
            "app-api", "/bin/app", "/srv",
            runtime_env={"APP_DATA": "/var/lib/app", "APP_QUOTE": 'a"b'},
        )
        self.assertIn('Environment="APP_DATA=/var/lib/app"', unit)
        self.assertIn('Environment="APP_QUOTE=a\\"b"', unit)


class TestComponentDescriptor(unittest.TestCase):
    def setUp(self):
        self.orch = DeploymentOrchestrator(base_dir="/var/www")

    def test_static_descriptor(self):
        dep = self.orch._component_dep(_static_component(), "/var/www/site")
        self.assertEqual(dep['project_type'], 'static')
        self.assertFalse(dep['needs_proxy'])
        self.assertEqual(dep['serve_path'], "/var/www/site/dist")
        self.assertEqual(dep['domain'], "example.com")
        self.assertIsNone(dep['backend_port'])

    def test_service_descriptor(self):
        dep = self.orch._component_dep(_service_component(), "/var/www/site")
        self.assertEqual(dep['project_type'], 'service')
        self.assertTrue(dep['needs_proxy'])
        self.assertEqual(dep['backend_port'], 8090)
        self.assertEqual(dep['proxy_port'], 8090)
        self.assertEqual(dep['domain'], "api.example.com")
        self.assertFalse(dep['api_subdomain'])
        self.assertTrue(dep['preserve_path'])

    def test_deploy_domain_placeholder(self):
        dep = self.orch._component_dep(
            _static_component(domain="{{domain}}"), "/var/www/site", "deployed.example"
        )
        self.assertEqual(dep['domain'], "deployed.example")

    def test_service_identity(self):
        unit, user = self.orch._service_identity("/var/www/example_com", _service_component())
        self.assertEqual(unit, "app-example_com-api")
        self.assertEqual(user, "app-example_com-api")

    def test_service_identity_caps_username(self):
        comp = _service_component(name="a-very-long-component-name-indeed")
        unit, user = self.orch._service_identity("/var/www/some_long_app_dir", comp)
        # systemd unit name keeps the full identity; the Linux username is capped.
        self.assertGreater(len(unit), 31)
        self.assertLessEqual(len(user), 31)
        self.assertTrue(user.startswith("app-"))

    def test_working_dir_defaults_to_release(self):
        ctx = self.orch._service_context(_service_component(), "/var/www/site")
        self.assertEqual(ctx['working_dir'], "/var/www/site")

    def test_working_dir_relative_resolved(self):
        comp = _service_component(working_dir="server")
        ctx = self.orch._service_context(comp, "/var/www/site")
        self.assertEqual(ctx['working_dir'], "/var/www/site/server")


class TestServiceContext(unittest.TestCase):
    def setUp(self):
        self.orch = DeploymentOrchestrator(base_dir="/var/www")

    def test_resolves_binary_working_dir_env_file(self):
        comp = _service_component(
            working_dir="{{release_dir}}/server",
            env_file="{{base_dir}}/{{name}}/.env",
        )
        ctx = self.orch._service_context(comp, "/var/www/shop")
        self.assertEqual(ctx['release_dir'], "/var/www/shop")
        self.assertEqual(ctx['base_dir'], "/var/www")
        self.assertEqual(ctx['port'], "8090")
        self.assertEqual(ctx['binary'], "/var/www/shop/server/app")
        self.assertEqual(ctx['working_dir'], "/var/www/shop/server")
        self.assertEqual(ctx['env_file'], "/var/www/api/.env")
        self.assertEqual(ctx['service_name'], "app-shop-api")
        # Dedicated user and managed dirs.
        self.assertEqual(ctx['web_user'], "app-shop-api")
        self.assertEqual(ctx['web_group'], "app-shop-api")
        self.assertEqual(ctx['shared_dir'], "/var/www/.infra_tools_shared/shop/api")
        self.assertEqual(ctx['data_dir'], "/var/www/.infra_tools_shared/shop/api/data")

    def test_shared_dir_can_be_referenced(self):
        comp = _service_component(env_file="{{shared_dir}}/.env")
        ctx = self.orch._service_context(comp, "/var/www/shop")
        self.assertEqual(ctx['env_file'], "/var/www/.infra_tools_shared/shop/api/.env")

    def test_deploy_domain_available_to_service_templates(self):
        comp = _service_component(domain="{{domain}}", env_file="{{base_dir}}/{{domain}}/.env")
        ctx = self.orch._service_context(comp, "/var/www/shop", "deployed.example")
        self.assertEqual(ctx['domain'], "deployed.example")
        self.assertEqual(ctx['env_file'], "/var/www/deployed.example/.env")

    def test_exec_component_context_has_no_binary(self):
        # With exec (and no binary field), {{binary}} is intentionally absent;
        # referencing it would fail fast at render time.
        comp = _service_component(binary=None, exec="/srv/app --port {{port}}")
        ctx = self.orch._service_context(comp, "/var/www/shop")
        self.assertNotIn('binary', ctx)
        self.assertEqual(ctx['port'], "8090")


class TestNginxIntegration(unittest.TestCase):
    """The descriptors must drive correct per-domain nginx config."""

    def setUp(self):
        self.orch = DeploymentOrchestrator(base_dir="/var/www")

    def test_static_site_served_from_output(self):
        dep = self.orch._component_dep(_static_component(), "/var/www/site")
        cfg = generate_merged_nginx_config("example.com", [dep], enable_https_redirect=False)
        self.assertIn("/var/www/site/dist", cfg)
        self.assertIn("server_name example.com;", cfg)

    def test_service_reverse_proxied_to_loopback_port(self):
        dep = self.orch._component_dep(_service_component(), "/var/www/site")
        cfg = generate_merged_nginx_config("api.example.com", [dep], enable_https_redirect=False)
        self.assertIn("proxy_pass http://127.0.0.1:8090", cfg)
        self.assertIn("server_name api.example.com;", cfg)

    def test_service_subpath_preserves_request_uri(self):
        dep = self.orch._component_dep(
            _service_component(domain="example.com", path="/api"), "/var/www/site"
        )
        cfg = generate_merged_nginx_config("example.com", [dep], enable_https_redirect=False)
        self.assertIn("location /api/", cfg)
        self.assertIn("proxy_pass http://127.0.0.1:8090;", cfg)


class TestDeployManifest(unittest.TestCase):
    def setUp(self):
        self.base_dir = tempfile.mkdtemp(prefix="manifest_base_")
        self.source = tempfile.mkdtemp(prefix="manifest_src_")
        self.orch = DeploymentOrchestrator(base_dir=self.base_dir)

        # A repo with a static site and a service, plus the artifacts a build
        # would have produced (so the binary-exists check passes).
        manifest = {
            "version": 1,
            "components": [
                {"name": "site", "type": "static", "domain": "example.com",
                 "build": "npm run build", "output": "dist"},
                {"name": "api", "type": "service", "domain": "api.example.com",
                 "build": "server/build.sh", "binary": "server/app",
                 "env_file": "/opt/app/.env",
                 "runtime_env": {"APP_DATA": "{{data_dir}}/app.sqlite3"},
                 "port": 8090, "health": "/health"},
            ],
        }
        with open(os.path.join(self.source, "infra.json"), "w") as f:
            json.dump(manifest, f)
        os.makedirs(os.path.join(self.source, "dist"))
        with open(os.path.join(self.source, "dist", "index.html"), "w") as f:
            f.write("<html></html>")
        os.makedirs(os.path.join(self.source, "server"))
        with open(os.path.join(self.source, "server", "app"), "w") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(self.source, "infra.json")) as f:
            self.manifest: Manifest = parse_manifest(json.load(f))

    def tearDown(self):
        for path in (self.base_dir, self.source):
            if os.path.exists(path):
                shutil.rmtree(path)

    @patch.object(DeploymentOrchestrator, '_poll_health')
    @patch('lib.deployment.create_managed_service')
    @patch('lib.deployment.save_deployment_metadata')
    @patch('lib.deployment.run')
    def test_deploys_all_components(self, mock_run, mock_meta, mock_service, mock_health):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        deps = self.orch.deploy_manifest(
            manifest=self.manifest,
            source_path=self.source,
            domain="example.com",
            path="/",
            git_url="https://git.example.com/shop.git",
            commit_hash="abc123",
            keep_source=True,
        )

        dest = os.path.join(self.base_dir, "example_com")

        # One descriptor per component, with the right shapes.
        self.assertEqual(len(deps), 2)
        by_domain = {d['domain']: d for d in deps}
        self.assertEqual(by_domain['example.com']['serve_path'], os.path.join(dest, "dist"))
        self.assertFalse(by_domain['example.com']['needs_proxy'])
        self.assertEqual(by_domain['api.example.com']['backend_port'], 8090)
        self.assertTrue(by_domain['api.example.com']['needs_proxy'])

        # Service was installed under its app-scoped name, as its dedicated user,
        # with the resolved binary path and env_file.
        mock_service.assert_called_once()
        args, kwargs = mock_service.call_args
        self.assertEqual(args[0], "app-example_com-api")           # service name
        self.assertEqual(args[1], os.path.join(dest, "server", "app"))  # exec_start
        self.assertEqual(args[3], "app-example_com-api")           # web_user (dedicated)
        self.assertEqual(args[4], "app-example_com-api")           # web_group
        self.assertEqual(kwargs['env_file'], "/opt/app/.env")
        self.assertEqual(
            kwargs['runtime_env'],
            {"APP_DATA": os.path.join(self.base_dir, ".infra_tools_shared", "example_com", "api", "data", "app.sqlite3")},
        )
        mock_health.assert_called_once()

        # The managed, service-owned data dir was created outside the release.
        data_dir = os.path.join(self.base_dir, ".infra_tools_shared", "example_com", "api", "data")
        self.assertTrue(os.path.isdir(data_dir))
        # A dedicated service user was ensured (id lookup attempted).
        self.assertTrue(any("id app-example_com-api" in c.args[0] for c in mock_run.call_args_list))

        # Both build commands ran at the release root.
        build_cmds = [c.args[0] for c in mock_run.call_args_list if "&&" in c.args[0]]
        self.assertTrue(any("npm run build" in c for c in build_cmds))
        self.assertTrue(any("server/build.sh" in c for c in build_cmds))

        # Metadata persisted, and the deployed tree is in place.
        mock_meta.assert_called_once()
        self.assertTrue(os.path.exists(os.path.join(dest, "infra.json")))

    @patch.object(DeploymentOrchestrator, '_poll_health')
    @patch('lib.deployment.create_managed_service')
    @patch('lib.deployment.save_deployment_metadata')
    @patch('lib.deployment.run')
    def test_build_failure_aborts(self, mock_run, mock_meta, mock_service, mock_health):
        # Fail only the build command; systemctl/chown calls succeed.
        def run_side_effect(cmd, *a, **k):
            if "npm run build" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="boom")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = run_side_effect

        with self.assertRaises(RuntimeError) as ctx:
            self.orch.deploy_manifest(
                manifest=self.manifest, source_path=self.source,
                domain="example.com", path="/",
                git_url="https://git.example.com/shop.git", commit_hash="abc123",
                keep_source=True,
            )
        self.assertIn("build failed", str(ctx.exception))

    @patch.object(DeploymentOrchestrator, '_poll_health')
    @patch('lib.deployment.create_managed_service')
    @patch('lib.deployment.save_deployment_metadata')
    @patch('lib.deployment.run')
    def test_build_failure_preserves_active_release(self, mock_run, mock_meta, mock_service, mock_health):
        active = os.path.join(self.base_dir, "example_com")
        os.makedirs(active)
        marker = os.path.join(active, "active-release.txt")
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("still serving")

        def run_side_effect(cmd, *a, **k):
            if "npm run build" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="broken build")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        with self.assertRaises(RuntimeError):
            self.orch.deploy_manifest(
                manifest=self.manifest, source_path=self.source,
                domain="example.com", path="/",
                git_url="https://git.example.com/shop.git", commit_hash="abc123",
                keep_source=True,
            )

        self.assertTrue(os.path.exists(marker))
        self.assertEqual(
            [name for name in os.listdir(self.base_dir) if name.startswith(".example_com.build-")],
            [],
        )

    @patch.object(DeploymentOrchestrator, '_poll_health')
    @patch('lib.deployment.create_managed_service')
    @patch('lib.deployment.save_deployment_metadata')
    @patch('lib.deployment.run')
    def test_missing_binary_aborts(self, mock_run, mock_meta, mock_service, mock_health):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        os.remove(os.path.join(self.source, "server", "app"))

        with self.assertRaises(RuntimeError) as ctx:
            self.orch.deploy_manifest(
                manifest=self.manifest, source_path=self.source,
                domain="example.com", path="/",
                git_url="https://git.example.com/shop.git", commit_hash="abc123",
                keep_source=True,
            )
        self.assertIn("binary not found", str(ctx.exception))


class TestDeployManifestUnitTemplate(unittest.TestCase):
    """A repo-supplied systemd_unit is installed as a substituted template."""

    def setUp(self):
        self.base_dir = tempfile.mkdtemp(prefix="manifest_base_")
        self.source = tempfile.mkdtemp(prefix="manifest_src_")
        self.orch = DeploymentOrchestrator(base_dir=self.base_dir)

        manifest = {
            "version": 1,
            "components": [
                {"name": "api", "type": "service", "domain": "api.example.com",
                 "build": "server/build.sh", "binary": "server/app",
                 "systemd_unit": "server/app.service.tmpl",
                 "env_file": "/opt/app/.env", "working_dir": "{{release_dir}}/server",
                 "port": 8090, "health": "/health"},
            ],
        }
        with open(os.path.join(self.source, "infra.json"), "w") as f:
            json.dump(manifest, f)
        os.makedirs(os.path.join(self.source, "server"))
        with open(os.path.join(self.source, "server", "app"), "w") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(self.source, "server", "app.service.tmpl"), "w") as f:
            f.write(
                "[Service]\n"
                "ExecStart={{binary}}\n"
                "WorkingDirectory={{working_dir}}\n"
                "EnvironmentFile={{env_file}}\n"
                "User={{web_user}}\n"
                "Environment=LISTEN_ADDR=:{{port}}\n"
            )
        with open(os.path.join(self.source, "infra.json")) as f:
            self.manifest: Manifest = parse_manifest(json.load(f))

    def tearDown(self):
        for path in (self.base_dir, self.source):
            if os.path.exists(path):
                shutil.rmtree(path)

    @patch.object(DeploymentOrchestrator, '_poll_health')
    @patch('lib.deployment.install_unit_file')
    @patch('lib.deployment.create_managed_service')
    @patch('lib.deployment.save_deployment_metadata')
    @patch('lib.deployment.run')
    def test_installs_rendered_unit(self, mock_run, mock_meta, mock_create, mock_install, mock_health):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        self.orch.deploy_manifest(
            manifest=self.manifest, source_path=self.source,
            domain="api.example.com", path="/",
            git_url="https://git.example.com/shop.git", commit_hash="abc123",
            keep_source=True,
        )

        dest = os.path.join(self.base_dir, "api_example_com")
        service_user = "app-api_example_com-api"

        # The generated-unit path must NOT be used when systemd_unit is present.
        mock_create.assert_not_called()
        mock_install.assert_called_once()
        service_name, rendered = mock_install.call_args.args
        self.assertEqual(service_name, service_user)
        # Placeholders resolved to deploy-time values, incl. the dedicated user.
        self.assertIn(f"ExecStart={os.path.join(dest, 'server', 'app')}", rendered)
        self.assertIn(f"WorkingDirectory={os.path.join(dest, 'server')}", rendered)
        self.assertIn("EnvironmentFile=/opt/app/.env", rendered)
        self.assertIn(f"User={service_user}", rendered)
        self.assertIn("LISTEN_ADDR=:8090", rendered)
        self.assertNotIn("{{", rendered)


if __name__ == "__main__":
    unittest.main()
