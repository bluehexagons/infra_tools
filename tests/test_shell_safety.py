"""Regression tests for shell-hardening changes tracked by REVIEW_1."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestShellSafety(unittest.TestCase):
    def test_repo_python_sources_do_not_use_shell_true(self):
        repo_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []

        for path in repo_root.rglob("*.py"):
            relative_parts = path.relative_to(repo_root).parts
            if any(part.startswith(".") for part in relative_parts):
                continue
            if "__pycache__" in relative_parts or path.name == "test_shell_safety.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and any(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                )
                for node in ast.walk(tree)
            ):
                offenders.append(str(path.relative_to(repo_root)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
