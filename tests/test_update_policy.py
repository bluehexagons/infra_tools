"""Tests for automatic update policy helpers."""

from __future__ import annotations

import unittest

from lib.update_policy import (
    ECOSYSTEM_AUTO_UPGRADE_ENV,
    NODE_LATEST_AUTO_UPDATE_ENV,
    ecosystem_auto_upgrade_enabled,
    env_flag_enabled,
    node_latest_auto_update_enabled,
)


class TestUpdatePolicy(unittest.TestCase):
    def test_env_flag_defaults_to_false(self):
        self.assertFalse(env_flag_enabled("MISSING", env={}))

    def test_env_flag_accepts_truthy_values(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(env_flag_enabled("FLAG", env={"FLAG": value}))

    def test_ecosystem_auto_upgrade_is_opt_in(self):
        self.assertFalse(ecosystem_auto_upgrade_enabled(env={}))
        self.assertTrue(ecosystem_auto_upgrade_enabled(env={ECOSYSTEM_AUTO_UPGRADE_ENV: "1"}))

    def test_node_latest_auto_update_is_opt_in(self):
        self.assertFalse(node_latest_auto_update_enabled(env={}))
        self.assertTrue(node_latest_auto_update_enabled(env={NODE_LATEST_AUTO_UPDATE_ENV: "yes"}))


if __name__ == "__main__":
    unittest.main()
