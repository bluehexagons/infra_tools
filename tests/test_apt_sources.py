"""Tests for APT source maintenance helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.apt_sources import disable_duplicate_vivaldi_source


VIVALDI_LIST = "deb https://repo.vivaldi.com/archive/deb/ stable main\n"
VIVALDI_SOURCES = """Types: deb
URIs: https://repo.vivaldi.com/archive/deb/
Suites: stable
Components: main
Signed-By: /usr/share/keyrings/vivaldi-browser.gpg
"""


class TestAptSources(unittest.TestCase):
    def test_disables_legacy_vivaldi_list_when_sources_also_exists(self):
        with tempfile.TemporaryDirectory() as sources_dir:
            list_path = os.path.join(sources_dir, "vivaldi.list")
            sources_path = os.path.join(sources_dir, "vivaldi.sources")
            with open(list_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(VIVALDI_LIST)
            with open(sources_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(VIVALDI_SOURCES)

            disabled_path = disable_duplicate_vivaldi_source(sources_dir)

            self.assertEqual(disabled_path, f"{list_path}.disabled-by-infra-tools")
            self.assertFalse(os.path.exists(list_path))
            self.assertTrue(os.path.exists(disabled_path))
            self.assertTrue(os.path.exists(sources_path))

    def test_ignores_single_vivaldi_source_file(self):
        with tempfile.TemporaryDirectory() as sources_dir:
            list_path = os.path.join(sources_dir, "vivaldi.list")
            with open(list_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(VIVALDI_LIST)

            disabled_path = disable_duplicate_vivaldi_source(sources_dir)

            self.assertIsNone(disabled_path)
            self.assertTrue(os.path.exists(list_path))

    def test_ignores_non_vivaldi_files_with_same_names(self):
        with tempfile.TemporaryDirectory() as sources_dir:
            list_path = os.path.join(sources_dir, "vivaldi.list")
            sources_path = os.path.join(sources_dir, "vivaldi.sources")
            with open(list_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("deb https://example.com/deb stable main\n")
            with open(sources_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("URIs: https://example.com/deb\n")

            disabled_path = disable_duplicate_vivaldi_source(sources_dir)

            self.assertIsNone(disabled_path)
            self.assertTrue(os.path.exists(list_path))
            self.assertTrue(os.path.exists(sources_path))

    def test_uses_numbered_disabled_path_when_default_exists(self):
        with tempfile.TemporaryDirectory() as sources_dir:
            list_path = os.path.join(sources_dir, "vivaldi.list")
            sources_path = os.path.join(sources_dir, "vivaldi.sources")
            disabled_path = f"{list_path}.disabled-by-infra-tools"
            with open(list_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(VIVALDI_LIST)
            with open(sources_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(VIVALDI_SOURCES)
            with open(disabled_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("previous cleanup\n")

            result = disable_duplicate_vivaldi_source(sources_dir)

            self.assertEqual(result, f"{disabled_path}.1")
            self.assertTrue(os.path.exists(result))


if __name__ == "__main__":
    unittest.main()
