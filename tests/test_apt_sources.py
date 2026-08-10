"""Tests for Debian APT source detection and offline-install repair."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from lib.apt_sources import (
    MANAGED_SOURCE_FILENAME,
    ensure_debian_package_sources,
    inspect_apt_sources,
    parse_apt_sources,
)


class TestAptSources(unittest.TestCase):
    def _layout(self, *, os_release: str, sources_list: str = "") -> tuple[str, str]:
        root = tempfile.mkdtemp()
        apt_dir = os.path.join(root, "etc", "apt")
        os.makedirs(os.path.join(apt_dir, "sources.list.d"))
        os.makedirs(os.path.join(root, "usr", "share", "keyrings"))
        release_path = os.path.join(root, "etc", "os-release")
        os.makedirs(os.path.dirname(release_path), exist_ok=True)
        with open(release_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(os_release)
        if sources_list:
            with open(os.path.join(apt_dir, "sources.list"), "w", encoding="utf-8") as file_obj:
                file_obj.write(sources_list)
        return root, apt_dir

    def test_repairs_cdrom_only_classic_sources(self):
        root, apt_dir = self._layout(
            os_release="ID=debian\nVERSION_CODENAME=trixie\n",
            sources_list="deb cdrom:[Debian GNU/Linux 13.0.0 _Trixie_ - Official amd64 DVD]/ trixie main\n",
        )
        try:
            import lib.apt_sources as apt_sources

            keyring = os.path.join(root, "usr", "share", "keyrings", "debian-archive-keyring.gpg")
            with open(keyring, "wb") as file_obj:
                file_obj.write(b"test keyring")
            original_keyring = apt_sources.DEBIAN_ARCHIVE_KEYRING
            apt_sources.DEBIAN_ARCHIVE_KEYRING = keyring
            try:
                status = ensure_debian_package_sources(apt_dir, os.path.join(root, "etc", "os-release"))
            finally:
                apt_sources.DEBIAN_ARCHIVE_KEYRING = original_keyring

            self.assertIsNotNone(status)
            assert status is not None
            self.assertTrue(status.has_official_base)
            self.assertTrue(status.has_official_security)
            self.assertFalse(status.cdrom_sources)
            with open(os.path.join(apt_dir, "sources.list"), encoding="utf-8") as file_obj:
                self.assertTrue(file_obj.read().startswith("# Disabled by infra_tools:"))
            managed_path = os.path.join(apt_dir, "sources.list.d", MANAGED_SOURCE_FILENAME)
            self.assertTrue(os.path.isfile(managed_path))
            self.assertTrue(os.path.isfile(os.path.join(apt_dir, "sources.list.infra_tools.bak")))
            self.assertEqual(len(parse_apt_sources(apt_dir)), 3)
        finally:
            shutil.rmtree(root)

    def test_accepts_existing_official_deb822_sources_and_disables_cdrom_stanza(self):
        root, apt_dir = self._layout(
            os_release="ID=debian\nVERSION_CODENAME=trixie\n",
        )
        try:
            import lib.apt_sources as apt_sources

            keyring = os.path.join(root, "usr", "share", "keyrings", "debian-archive-keyring.gpg")
            with open(keyring, "wb") as file_obj:
                file_obj.write(b"test keyring")
            sources_path = os.path.join(apt_dir, "sources.list.d", "debian.sources")
            with open(sources_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "Types: deb\nURIs: cdrom:[Debian]/\nSuites: trixie\n"
                    "Components: main\n\n"
                    "Types: deb\nURIs: http://deb.debian.org/debian\n"
                    "Suites: trixie trixie-updates\nComponents: main\n\n"
                    "Types: deb\nURIs: http://security.debian.org\n"
                    "Suites: trixie-security\nComponents: main\n"
                )
            original_keyring = apt_sources.DEBIAN_ARCHIVE_KEYRING
            apt_sources.DEBIAN_ARCHIVE_KEYRING = keyring
            try:
                status = ensure_debian_package_sources(apt_dir, os.path.join(root, "etc", "os-release"))
            finally:
                apt_sources.DEBIAN_ARCHIVE_KEYRING = original_keyring

            self.assertIsNotNone(status)
            assert status is not None
            self.assertTrue(status.has_official_base)
            self.assertTrue(status.has_official_security)
            self.assertFalse(status.cdrom_sources)
            with open(sources_path, encoding="utf-8") as file_obj:
                self.assertIn("# Disabled by infra_tools: URIs: cdrom:[Debian]/", file_obj.read())
            self.assertFalse(os.path.exists(os.path.join(apt_dir, "sources.list.d", MANAGED_SOURCE_FILENAME)))
        finally:
            shutil.rmtree(root)

    def test_rejects_non_debian_source_repair(self):
        root, apt_dir = self._layout(os_release="ID=ubuntu\nVERSION_CODENAME=noble\n")
        try:
            self.assertIsNone(
                ensure_debian_package_sources(apt_dir, os.path.join(root, "etc", "os-release"))
            )
            self.assertEqual(inspect_apt_sources("noble", apt_dir).entries, ())
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
