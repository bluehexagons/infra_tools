"""Tests for patch_setup CLI help output."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import patch_setup


class TestPatchSetupHelp(unittest.TestCase):
    def test_help_lists_special_patch_commands(self):
        help_text = patch_setup.create_patch_argument_parser().format_help()

        self.assertIn("Special commands:", help_text)
        self.assertIn("patch_setup.py list [pattern]", help_text)
        self.assertIn("patch_setup.py info [pattern]", help_text)
        self.assertIn("patch_setup.py rm [pattern]", help_text)
        self.assertIn("patch_setup.py deploy [pattern]", help_text)


if __name__ == "__main__":
    unittest.main()
