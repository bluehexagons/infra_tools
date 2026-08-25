"""Tests for generic static-site publication on the internal HTTPS host."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.service_tools import static_web_publish


def _args(project: str, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "json": False,
        "no_build": True,
        "no_install": False,
        "open": False,
        "output": "dist",
        "project_option": project,
        "project_positional": None,
        "site": "demo",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestStaticWebPublish(unittest.TestCase):
    def test_publishes_existing_output_atomically_and_updates_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = os.path.join(temporary_dir, "project")
            output = os.path.join(project, "dist")
            sites_root = os.path.join(temporary_dir, "sites")
            user_root = os.path.join(sites_root, "agent")
            os.makedirs(output)
            os.makedirs(user_root)
            with open(os.path.join(project, "package.json"), "w", encoding="utf-8") as file_obj:
                json.dump({"name": "demo-site"}, file_obj)
            with open(os.path.join(output, "index.html"), "w", encoding="utf-8") as file_obj:
                file_obj.write("new site")
            old_site = os.path.join(user_root, "demo")
            os.mkdir(old_site)
            with open(os.path.join(old_site, "index.html"), "w", encoding="utf-8") as file_obj:
                file_obj.write("old site")
            url_file = os.path.join(temporary_dir, "base-url")
            with open(url_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("https://sites.example:8443\n")
            account = SimpleNamespace(pw_name="agent", pw_uid=os.getuid())

            with (
                patch.object(static_web_publish, "SITES_ROOT", sites_root),
                patch.object(static_web_publish, "BASE_URL_FILE", url_file),
                patch.object(static_web_publish, "_current_account", return_value=account),
            ):
                result = static_web_publish.publish(_args(project))

            self.assertTrue(result["ok"])
            self.assertEqual(result["url"], "https://sites.example:8443/sites/agent/demo/")
            with open(os.path.join(old_site, "index.html"), encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "new site")
            self.assertTrue(os.path.isfile(os.path.join(old_site, ".infra-tools.json")))
            with open(os.path.join(user_root, "index.html"), encoding="utf-8") as file_obj:
                self.assertIn("demo-site", file_obj.read())

    def test_build_installs_missing_dependencies_and_runs_package_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = os.path.join(temporary_dir, "project")
            output = os.path.join(project, "dist")
            os.makedirs(project)
            with open(os.path.join(project, "package.json"), "w", encoding="utf-8") as file_obj:
                json.dump({"name": "demo", "scripts": {"build": "vite build"}}, file_obj)
            with open(os.path.join(project, "package-lock.json"), "w", encoding="utf-8"):
                pass

            commands: list[list[str]] = []

            def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                commands.append(command)
                if command == ["npm", "run", "build"]:
                    os.mkdir(output)
                    with open(os.path.join(output, "index.html"), "w", encoding="utf-8"):
                        pass
                return SimpleNamespace(returncode=0)

            with patch.object(static_web_publish.subprocess, "run", side_effect=run):
                static_web_publish._run_project_build(project, {"scripts": {"build": "vite"}}, install=True)

            self.assertEqual(commands, [["npm", "ci"], ["npm", "run", "build"]])

    def test_rejects_symlinks_in_static_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = os.path.join(temporary_dir, "dist")
            os.mkdir(output)
            with open(os.path.join(output, "index.html"), "w", encoding="utf-8"):
                pass
            os.symlink("index.html", os.path.join(output, "linked.html"))

            with self.assertRaisesRegex(ValueError, "symlink"):
                static_web_publish._validate_output_tree(output)

    def test_remove_requires_confirmation_and_owned_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            sites_root = os.path.join(temporary_dir, "sites")
            user_root = os.path.join(sites_root, "agent")
            site = os.path.join(user_root, "demo")
            os.makedirs(site)
            account = SimpleNamespace(pw_name="agent", pw_uid=os.getuid())
            with patch.object(static_web_publish, "SITES_ROOT", sites_root):
                with self.assertRaisesRegex(ValueError, "requires --yes"):
                    static_web_publish.remove_site(account, "demo", False)
                static_web_publish.remove_site(account, "demo", True)

            self.assertFalse(os.path.exists(site))


if __name__ == "__main__":
    unittest.main()
