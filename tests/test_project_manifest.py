"""Tests for lib/project_manifest.py: infra.json parsing and validation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.project_manifest import (
    MANIFEST_FILENAME,
    Manifest,
    has_placeholder,
    load_manifest,
    parse_manifest,
    render_template,
)


def _static(**overrides: object) -> dict:
    base = {
        "name": "site",
        "type": "static",
        "domain": "example.com",
        "build": "npm ci && npm run build",
        "output": "dist",
    }
    base.update(overrides)
    return base


def _service(**overrides: object) -> dict:
    base = {
        "name": "api",
        "type": "service",
        "domain": "api.example.com",
        "build": "server/deploy/build.sh",
        "binary": "server/app",
        "port": 8080,
    }
    base.update(overrides)
    return base


def _manifest(*components: dict, version: object = 1) -> dict:
    return {"version": version, "components": list(components)}


class TestValidParse(unittest.TestCase):
    def test_multi_component(self):
        manifest = parse_manifest(_manifest(_static(), _service()))
        self.assertIsInstance(manifest, Manifest)
        self.assertEqual(manifest.version, 1)
        self.assertEqual([c.name for c in manifest.components], ["site", "api"])

        site, api = manifest.components
        self.assertTrue(site.is_static)
        self.assertEqual(site.output, "dist")
        self.assertEqual(site.path, "/")  # default
        self.assertEqual(site.build, ["npm ci && npm run build"])

        self.assertTrue(api.is_service)
        self.assertEqual(api.port, 8080)
        self.assertEqual(api.binary, "server/app")
        self.assertTrue(api.reverse_proxy)  # default

    def test_build_as_array(self):
        comp = parse_manifest(_manifest(_static(build=["a", "b"]))).components[0]
        self.assertEqual(comp.build, ["a", "b"])

    def test_build_omitted(self):
        comp = parse_manifest(_manifest(_static(build=None))).components[0]
        self.assertEqual(comp.build, [])

    def test_env_parsed(self):
        comp = parse_manifest(_manifest(_static(env={"VITE_SHOP": "1"}))).components[0]
        self.assertEqual(comp.env, {"VITE_SHOP": "1"})

    def test_service_with_exec_instead_of_binary(self):
        comp = parse_manifest(
            _manifest(_service(binary=None, exec="/usr/bin/app --serve"))
        ).components[0]
        self.assertIsNone(comp.binary)
        self.assertEqual(comp.exec, "/usr/bin/app --serve")

    def test_service_optional_fields(self):
        comp = parse_manifest(
            _manifest(
                _service(
                    systemd_unit="server/deploy/app.service",
                    env_file="/opt/app/.env",
                    health="/api/health",
                    reverse_proxy=False,
                    working_dir="server",
                )
            )
        ).components[0]
        self.assertEqual(comp.systemd_unit, "server/deploy/app.service")
        self.assertEqual(comp.env_file, "/opt/app/.env")
        self.assertEqual(comp.health, "/api/health")
        self.assertFalse(comp.reverse_proxy)
        self.assertEqual(comp.working_dir, "server")


class TestRejects(unittest.TestCase):
    def _assert_rejected(self, data: object, needle: str = "") -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_manifest(data)
        if needle:
            self.assertIn(needle, str(ctx.exception))

    def test_not_an_object(self):
        self._assert_rejected([], "must be a JSON object")

    def test_bad_version(self):
        self._assert_rejected(_manifest(_static(), version=2), "version")

    def test_missing_version(self):
        self._assert_rejected({"components": [_static()]}, "version")

    def test_empty_components(self):
        self._assert_rejected(_manifest(), "non-empty")

    def test_components_not_array(self):
        self._assert_rejected({"version": 1, "components": {}}, "non-empty")

    def test_duplicate_names(self):
        self._assert_rejected(
            _manifest(_static(name="dup"), _service(name="dup")), "duplicate"
        )

    def test_unknown_type(self):
        self._assert_rejected(_manifest(_static(type="lambda")), "static' or 'service")

    def test_missing_required_field(self):
        comp = _static()
        del comp["output"]
        self._assert_rejected(_manifest(comp), "output")

    def test_missing_domain(self):
        comp = _static()
        del comp["domain"]
        self._assert_rejected(_manifest(comp), "domain")

    def test_invalid_domain(self):
        self._assert_rejected(_manifest(_static(domain="not a host")), "domain")

    def test_domain_placeholder_accepted(self):
        comp = parse_manifest(_manifest(_static(domain="{{domain}}"))).components[0]
        self.assertEqual(comp.domain, "{{domain}}")

    def test_invalid_name(self):
        self._assert_rejected(_manifest(_static(name="Site_1")), "name")

    def test_unknown_field(self):
        self._assert_rejected(_manifest(_static(extra="x")), "unknown field")

    def test_top_level_unknown_field(self):
        data = _manifest(_static())
        data["extras"] = True
        self._assert_rejected(data, "unknown field")

    def test_output_escapes_root(self):
        self._assert_rejected(_manifest(_static(output="../etc")), "escape")

    def test_output_absolute(self):
        self._assert_rejected(_manifest(_static(output="/etc/passwd")), "relative")

    def test_binary_escapes_root(self):
        self._assert_rejected(_manifest(_service(binary="../../bin/sh")), "escape")

    def test_port_out_of_range(self):
        self._assert_rejected(_manifest(_service(port=80)), "between")

    def test_port_too_high(self):
        self._assert_rejected(_manifest(_service(port=70000)), "between")

    def test_port_not_int(self):
        self._assert_rejected(_manifest(_service(port="8080")), "integer")

    def test_port_bool_rejected(self):
        self._assert_rejected(_manifest(_service(port=True)), "integer")

    def test_service_both_binary_and_exec(self):
        self._assert_rejected(
            _manifest(_service(exec="run")), "exactly one"
        )

    def test_service_neither_binary_nor_exec(self):
        self._assert_rejected(_manifest(_service(binary=None)), "exactly one")

    def test_env_file_not_absolute(self):
        self._assert_rejected(_manifest(_service(env_file="relative/.env")), "absolute")

    def test_env_value_not_string(self):
        self._assert_rejected(_manifest(_static(env={"K": 1})), "must be a string")

    def test_build_empty_string(self):
        self._assert_rejected(_manifest(_static(build="  ")), "non-empty")

    def test_build_wrong_type(self):
        self._assert_rejected(_manifest(_static(build=5)), "string or array")

    def test_path_without_leading_slash(self):
        self._assert_rejected(_manifest(_static(path="sub")), "path")

    def test_health_without_leading_slash(self):
        self._assert_rejected(_manifest(_service(health="health")), "health")

    def test_reverse_proxy_not_bool(self):
        self._assert_rejected(_manifest(_service(reverse_proxy="yes")), "boolean")


class TestTemplating(unittest.TestCase):
    def test_render_substitutes(self):
        out = render_template(
            "{{base_dir}}/{{name}}/.env",
            {"base_dir": "/var/www", "name": "api"},
        )
        self.assertEqual(out, "/var/www/api/.env")

    def test_render_allows_inner_whitespace(self):
        self.assertEqual(render_template("{{ port }}", {"port": "8080"}), "8080")

    def test_render_unknown_variable_raises(self):
        with self.assertRaises(ValueError) as ctx:
            render_template("{{nope}}", {"port": "8080"})
        self.assertIn("nope", str(ctx.exception))

    def test_render_no_placeholder_unchanged(self):
        self.assertEqual(render_template("/opt/app/.env", {}), "/opt/app/.env")

    def test_has_placeholder(self):
        self.assertTrue(has_placeholder("{{base_dir}}/x"))
        self.assertFalse(has_placeholder("/opt/app"))


class TestTemplatedFieldValidation(unittest.TestCase):
    def _assert_rejected(self, data: object, needle: str = "") -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_manifest(data)
        if needle:
            self.assertIn(needle, str(ctx.exception))

    def test_env_file_with_placeholder_accepted(self):
        comp = parse_manifest(
            _manifest(_service(env_file="{{base_dir}}/{{name}}/.env"))
        ).components[0]
        self.assertEqual(comp.env_file, "{{base_dir}}/{{name}}/.env")

    def test_env_file_relative_without_placeholder_rejected(self):
        self._assert_rejected(_manifest(_service(env_file="relative/.env")), "absolute")

    def test_env_file_unknown_placeholder_rejected(self):
        self._assert_rejected(
            _manifest(_service(env_file="{{bogus}}/.env")), "unknown template variable"
        )

    def test_exec_placeholders_accepted(self):
        comp = parse_manifest(
            _manifest(_service(binary=None, exec="{{binary}} --port {{port}}"))
        ).components[0]
        self.assertEqual(comp.exec, "{{binary}} --port {{port}}")

    def test_exec_unknown_placeholder_rejected(self):
        self._assert_rejected(
            _manifest(_service(binary=None, exec="{{wat}}")), "unknown template variable"
        )

    def test_working_dir_placeholder_accepted(self):
        comp = parse_manifest(
            _manifest(_service(working_dir="{{release_dir}}/server"))
        ).components[0]
        self.assertEqual(comp.working_dir, "{{release_dir}}/server")

    def test_working_dir_unknown_placeholder_rejected(self):
        self._assert_rejected(
            _manifest(_service(working_dir="{{nope}}")), "unknown template variable"
        )


class TestLoadManifest(unittest.TestCase):
    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as repo:
            self.assertIsNone(load_manifest(repo))

    def test_loads_from_disk(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, MANIFEST_FILENAME), "w", encoding="utf-8") as f:
                json.dump(_manifest(_static(), _service()), f)
            manifest = load_manifest(repo)
            assert manifest is not None
            self.assertEqual(len(manifest.components), 2)

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, MANIFEST_FILENAME), "w", encoding="utf-8") as f:
                f.write("{ not json")
            with self.assertRaises(ValueError) as ctx:
                load_manifest(repo)
            self.assertIn("invalid JSON", str(ctx.exception))

    def test_bluehexagons_example(self):
        """The shipped bluehexagons infra.json must validate, if present."""
        repo = os.path.join(os.path.dirname(__file__), "..", "..", "bluehexagons")
        manifest_path = os.path.join(repo, MANIFEST_FILENAME)
        if not os.path.exists(manifest_path):
            self.skipTest("bluehexagons repo not checked out alongside infra_tools")
        manifest = load_manifest(repo)
        assert manifest is not None
        names = {c.name for c in manifest.components}
        self.assertEqual(names, {"site"})
        self.assertEqual(manifest.components[0].domain, "{{domain}}")


if __name__ == "__main__":
    unittest.main()
