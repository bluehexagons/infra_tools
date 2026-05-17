"""Tests for automatic update policy helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from lib.update_policy import (
    DEFAULT_DEPENDENCY_MIN_AGE_DAYS,
    DEPENDENCY_MIN_AGE_DAYS_ENV,
    ECOSYSTEM_AUTO_UPGRADE_ENV,
    NODE_LATEST_AUTO_UPDATE_ENV,
    dependency_exclude_newer_cutoff,
    dependency_min_age_days,
    ecosystem_auto_upgrade_enabled,
    env_flag_enabled,
    node_latest_auto_update_enabled,
    npm_freshness_args,
    uv_exclude_newer_args,
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

    def test_dependency_min_age_defaults_to_seven_days(self):
        self.assertEqual(dependency_min_age_days(env={}), DEFAULT_DEPENDENCY_MIN_AGE_DAYS)

    def test_dependency_exclude_newer_cutoff_uses_min_age(self):
        cutoff = dependency_exclude_newer_cutoff(
            now=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            env={DEPENDENCY_MIN_AGE_DAYS_ENV: "3"},
        )
        self.assertEqual(cutoff, "2026-05-14T12:00:00Z")

    def test_dependency_min_age_zero_disables_freshness_args(self):
        env = {DEPENDENCY_MIN_AGE_DAYS_ENV: "0"}
        self.assertIsNone(dependency_exclude_newer_cutoff(env=env))
        self.assertEqual(npm_freshness_args(env=env), [])
        self.assertEqual(uv_exclude_newer_args(env=env), [])

    def test_dependency_min_age_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            dependency_min_age_days(env={DEPENDENCY_MIN_AGE_DAYS_ENV: "soon"})
        with self.assertRaisesRegex(ValueError, "must be 0 or greater"):
            dependency_min_age_days(env={DEPENDENCY_MIN_AGE_DAYS_ENV: "-1"})


if __name__ == "__main__":
    unittest.main()
