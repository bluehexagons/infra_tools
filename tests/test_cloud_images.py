"""Tests for lib/cloud_images.py: catalog resolution and --image parsing."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.cloud_images import (
    CLOUD_IMAGES,
    is_local_image_ref,
    parse_image_argument,
    resolve_cloud_image,
)


class TestResolveCloudImage(unittest.TestCase):
    def test_default_debian(self):
        entry = resolve_cloud_image("debian")
        self.assertEqual(entry["codename"], "trixie")
        self.assertEqual(entry["version"], "13")
        self.assertEqual(entry, CLOUD_IMAGES["debian-13"])
        self.assertTrue(entry["url"].startswith("https://cloud.debian.org/"))
        self.assertRegex(entry["snapshot"], r"^\d{8}-\d{3,4}$")
        self.assertRegex(entry["sha512"], r"^[0-9a-f]{128}$")

    def test_case_insensitive(self):
        self.assertEqual(
            resolve_cloud_image("Debian-12")["codename"],
            CLOUD_IMAGES["debian-12"]["codename"],
        )
        self.assertEqual(resolve_cloud_image("Debian-13"), resolve_cloud_image("debian"))

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            resolve_cloud_image("ubuntu")

    def test_empty_falls_back_to_default(self):
        self.assertEqual(resolve_cloud_image("")["codename"], "trixie")


class TestParseImageArgument(unittest.TestCase):
    def test_url(self):
        self.assertEqual(
            parse_image_argument("https://example.com/foo.qcow2"),
            ("https://example.com/foo.qcow2", None),
        )

    def test_storage_ref(self):
        self.assertEqual(
            parse_image_argument("local:iso/foo.img"),
            (None, "local:iso/foo.img"),
        )
        self.assertEqual(
            parse_image_argument("local:import/foo.qcow2"),
            (None, "local:import/foo.qcow2"),
        )

    def test_qcow2_iso_ref_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"import.*content type"):
            parse_image_argument("local:iso/foo.qcow2")

    def test_empty(self):
        self.assertEqual(parse_image_argument(""), (None, None))
        self.assertEqual(parse_image_argument(None), (None, None))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_image_argument("not-a-url-or-ref.qcow2")
        with self.assertRaises(ValueError):
            parse_image_argument("http://example.com/foo.qcow2")
        with self.assertRaises(ValueError):
            parse_image_argument("local:")


class TestIsLocalImageRef(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_local_image_ref("local:iso/foo.img"))
        self.assertTrue(is_local_image_ref("nfs-store:iso/x/y.img"))
        self.assertTrue(is_local_image_ref("local:import/foo.qcow2"))

    def test_invalid(self):
        self.assertFalse(is_local_image_ref(""))
        self.assertFalse(is_local_image_ref("local:"))
        self.assertFalse(is_local_image_ref("foo.qcow2"))
        self.assertFalse(is_local_image_ref(":iso/foo.qcow2"))


if __name__ == "__main__":
    unittest.main()
