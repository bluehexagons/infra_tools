"""Regression tests for shell-hardening changes tracked by REVIEW_1."""

from __future__ import annotations

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
            if any(part.startswith(".") for part in path.relative_to(repo_root).parts):
                continue
            if path.name in {"__pycache__", "test_shell_safety.py"}:
                continue
            content = path.read_text(encoding="utf-8")
            if "shell=True" in content:
                offenders.append(str(path.relative_to(repo_root)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
