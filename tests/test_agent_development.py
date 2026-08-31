"""Tests for managed development-toolchain readiness."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import agent_cli


class AgentDevelopmentReadinessTests(unittest.TestCase):
    def test_node_readiness_reports_missing_pnpm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            nvm_dir = home / ".nvm"
            node_bin = nvm_dir / "versions" / "node" / "v24.20.0" / "bin"
            node_bin.mkdir(parents=True)
            (nvm_dir / "nvm.sh").write_text("# nvm\n", encoding="utf-8")
            for name in ("node", "npm", "corepack"):
                (node_bin / name).write_text("", encoding="utf-8")

            def version(path: str, *_arguments: str) -> str | None:
                return {
                    "node": "v24.20.0",
                    "npm": "11.19.0",
                    "corepack": "0.35.0",
                }.get(os.path.basename(path))

            with (
                patch.object(agent_cli, "_nvm_node_bin", return_value=str(node_bin)),
                patch.object(agent_cli, "_command_version", side_effect=version),
            ):
                result = agent_cli._inspect_node_development(str(home))

        self.assertFalse(result["healthy"])
        self.assertEqual(result["issues"], ["node_pnpm_missing"])
        self.assertEqual(result["version"], "v24.20.0")

    def test_development_readiness_ignores_absent_optional_toolchains(self) -> None:
        healthy_node = {
            "installed": True,
            "healthy": True,
            "version": "v24.20.0",
            "issues": [],
        }
        absent = {"installed": False, "healthy": True, "issues": []}
        with (
            patch.object(
                agent_cli,
                "_inspect_godot_development",
                return_value=absent,
            ),
            patch.object(agent_cli, "_inspect_go_development", return_value=absent),
            patch.object(
                agent_cli,
                "_inspect_node_development",
                return_value=healthy_node,
            ),
        ):
            result = agent_cli.inspect_development_readiness("/home/agent")

        self.assertTrue(result["installed"])
        self.assertTrue(result["healthy"])
        self.assertEqual(result["issues"], [])


if __name__ == "__main__":
    unittest.main()
