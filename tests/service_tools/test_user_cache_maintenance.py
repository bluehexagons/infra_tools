"""Tests for common.service_tools.user_cache_maintenance."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from common.service_tools import user_cache_maintenance


class TestUserCacheHelpers(unittest.TestCase):
    def _context(self, home: str) -> user_cache_maintenance.UserContext:
        return user_cache_maintenance.UserContext("agent", home, 1000)

    def test_cache_usage_counts_files_without_following_links(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            cache_dir = os.path.join(home, "cache")
            os.mkdir(cache_dir)
            with open(os.path.join(cache_dir, "data"), "w", encoding="utf-8") as handle:
                handle.write("data")
            with open(os.path.join(outside, "large"), "w", encoding="utf-8") as handle:
                handle.write("not part of the cache")
            os.symlink(outside, os.path.join(cache_dir, "outside"))

            usage = user_cache_maintenance.cache_usage(cache_dir)

            self.assertEqual(usage.size_bytes, 4)
            self.assertIsNotNone(usage.newest_mtime)

    def test_managed_path_must_remain_inside_home(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            context = self._context(home)

            self.assertTrue(
                user_cache_maintenance.is_safe_managed_path(
                    context,
                    os.path.join(home, ".cache", "tool"),
                    "tool",
                )
            )
            self.assertFalse(
                user_cache_maintenance.is_safe_managed_path(
                    context,
                    outside,
                    "tool",
                )
            )
            self.assertFalse(
                user_cache_maintenance.is_safe_managed_path(context, home, "tool")
            )

    @patch("common.service_tools.user_cache_maintenance.subprocess.run")
    def test_tool_command_loads_home_scoped_nvm(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        context = self._context("/home/agent")

        user_cache_maintenance.run_tool_command(
            context,
            ["npm", "cache", "verify"],
            load_nvm=True,
        )

        command = mock_run.call_args.args[0]
        self.assertEqual(command[:2], ["/bin/bash", "-lc"])
        self.assertIn("export NVM_DIR=/home/agent/.nvm", command[2])
        self.assertIn('"$NVM_DIR/nvm.sh"', command[2])
        self.assertIn("exec npm cache verify", command[2])
        self.assertEqual(mock_run.call_args.kwargs["cwd"], "/home/agent")
        self.assertEqual(mock_run.call_args.kwargs["env"]["HOME"], "/home/agent")

    @patch("common.service_tools.user_cache_maintenance.run_tool_command")
    def test_query_cache_path_uses_first_available_tool(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess([], 77, "", ""),
            subprocess.CompletedProcess([], 0, "/home/agent/.cache/pip\n", ""),
        ]

        path, executable, failure = user_cache_maintenance.query_cache_path(
            self._context("/home/agent"),
            (["pip3", "cache", "dir"], ["pip", "cache", "dir"]),
            "pip cache path query",
        )

        self.assertEqual(path, "/home/agent/.cache/pip")
        self.assertEqual(executable, "pip")
        self.assertIsNone(failure)

    def test_active_tool_detection_reads_process_name_only(self):
        with tempfile.TemporaryDirectory() as proc_root:
            process_dir = os.path.join(proc_root, "123")
            os.mkdir(process_dir)
            with open(os.path.join(process_dir, "comm"), "w", encoding="utf-8") as handle:
                handle.write("codex-x86_64\n")

            self.assertTrue(
                user_cache_maintenance.tool_is_active(("codex",), proc_root=proc_root)
            )
            self.assertFalse(
                user_cache_maintenance.tool_is_active(("opencode",), proc_root=proc_root)
            )

    @patch("common.service_tools.user_cache_maintenance.tool_is_active", return_value=False)
    def test_managed_cache_removes_only_allowlisted_directory(self, _active):
        with tempfile.TemporaryDirectory() as home:
            context = self._context(home)
            cache_dir = os.path.join(home, ".cache", "opencode")
            state_dir = os.path.join(home, ".local", "share", "opencode")
            os.makedirs(cache_dir)
            os.makedirs(state_dir)
            with open(os.path.join(cache_dir, "cache"), "w", encoding="utf-8") as handle:
                handle.write("cache")
            with open(os.path.join(state_dir, "auth.json"), "w", encoding="utf-8") as handle:
                handle.write("preserve")

            failures = user_cache_maintenance.cleanup_managed_directory(
                context,
                label="OpenCode",
                path=cache_dir,
                max_bytes=1,
                max_age_days=90,
                process_names=("opencode",),
                dry_run=False,
            )

            self.assertEqual(failures, [])
            self.assertFalse(os.path.exists(cache_dir))
            self.assertTrue(os.path.exists(os.path.join(state_dir, "auth.json")))

    @patch("common.service_tools.user_cache_maintenance.tool_is_active", return_value=True)
    def test_managed_cache_defers_while_tool_is_active(self, _active):
        with tempfile.TemporaryDirectory() as home:
            context = self._context(home)
            cache_dir = os.path.join(home, ".codex", "cache")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "entry"), "w", encoding="utf-8") as handle:
                handle.write("cache")

            failures = user_cache_maintenance.cleanup_managed_directory(
                context,
                label="Codex",
                path=cache_dir,
                max_bytes=1,
                max_age_days=90,
                process_names=("codex",),
                dry_run=False,
            )

            self.assertEqual(failures, [])
            self.assertTrue(os.path.exists(cache_dir))

    @patch("common.service_tools.user_cache_maintenance.tool_is_active", return_value=False)
    def test_managed_cache_dry_run_preserves_directory(self, _active):
        with tempfile.TemporaryDirectory() as home:
            context = self._context(home)
            cache_dir = os.path.join(home, ".cache", "opencode")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "entry"), "w", encoding="utf-8") as handle:
                handle.write("cache")

            user_cache_maintenance.cleanup_managed_directory(
                context,
                label="OpenCode",
                path=cache_dir,
                max_bytes=1,
                max_age_days=90,
                process_names=("opencode",),
                dry_run=True,
            )

            self.assertTrue(os.path.exists(cache_dir))

    @patch("common.service_tools.user_cache_maintenance.tool_is_active", return_value=False)
    def test_stale_temp_cleanup_preserves_fresh_entries_and_links(self, _active):
        with tempfile.TemporaryDirectory() as home:
            context = self._context(home)
            tmp_dir = os.path.join(home, ".codex", "tmp")
            os.makedirs(tmp_dir)
            old_file = os.path.join(tmp_dir, "old")
            fresh_file = os.path.join(tmp_dir, "fresh")
            linked_file = os.path.join(tmp_dir, "linked")
            for path in (old_file, fresh_file):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("x")
            os.symlink(old_file, linked_file)
            old_time = time.time() - (8 * 24 * 60 * 60)
            os.utime(old_file, (old_time, old_time))

            failures = user_cache_maintenance.cleanup_stale_children(
                context,
                label="Codex temporary files",
                path=tmp_dir,
                max_age_days=7,
                process_names=("codex",),
                dry_run=False,
            )

            self.assertEqual(failures, [])
            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(fresh_file))
            self.assertTrue(os.path.islink(linked_file))


class TestUserCachePolicies(unittest.TestCase):
    def setUp(self):
        self.context = user_cache_maintenance.UserContext("agent", "/home/agent", 1000)

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_npm_verifies_and_cleans_only_when_oversized(
        self,
        mock_query,
        mock_inventory,
        mock_cleanup,
    ):
        mock_query.return_value = ("/home/agent/.npm", "npm", None)
        oversized = user_cache_maintenance.CacheUsage(
            user_cache_maintenance.NPM_CACHE_MAX_BYTES + 1,
            time.time(),
        )
        mock_inventory.side_effect = [(oversized, None), (oversized, None)]

        failures = user_cache_maintenance.cleanup_npm_cache(self.context, dry_run=False)

        self.assertEqual(failures, [])
        self.assertEqual(mock_cleanup.call_count, 2)
        self.assertEqual(mock_cleanup.call_args_list[0].args[1], ["npm", "cache", "verify"])
        self.assertEqual(
            mock_cleanup.call_args_list[1].args[1],
            ["npm", "cache", "clean", "--force"],
        )

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_npm_remeasures_after_verify_before_forced_cleanup(
        self,
        mock_query,
        mock_inventory,
        mock_cleanup,
    ):
        mock_query.return_value = ("/home/agent/.npm", "npm", None)
        mock_inventory.side_effect = [
            (
                user_cache_maintenance.CacheUsage(
                    user_cache_maintenance.NPM_CACHE_MAX_BYTES + 1,
                    time.time(),
                ),
                None,
            ),
            (user_cache_maintenance.CacheUsage(10, time.time()), None),
        ]

        failures = user_cache_maintenance.cleanup_npm_cache(
            self.context,
            dry_run=False,
        )

        self.assertEqual(failures, [])
        mock_cleanup.assert_called_once_with(
            self.context,
            ["npm", "cache", "verify"],
            "npm cache verification and garbage collection",
            dry_run=False,
            load_nvm=True,
        )

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command")
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_pip_below_limit_is_inventory_only(self, mock_query, mock_inventory, mock_cleanup):
        mock_query.return_value = ("/home/agent/.cache/pip", "pip3", None)
        mock_inventory.return_value = (
            user_cache_maintenance.CacheUsage(10, time.time()),
            None,
        )

        failures = user_cache_maintenance.cleanup_pip_cache(self.context, dry_run=False)

        self.assertEqual(failures, [])
        mock_cleanup.assert_not_called()

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_uv_uses_supported_prune_command(self, mock_query, mock_inventory, mock_cleanup):
        mock_query.return_value = ("/home/agent/.cache/uv", "uv", None)
        mock_inventory.return_value = (
            user_cache_maintenance.CacheUsage(10, time.time()),
            None,
        )

        failures = user_cache_maintenance.cleanup_uv_cache(self.context, dry_run=False)

        self.assertEqual(failures, [])
        mock_cleanup.assert_called_once_with(
            self.context,
            ["uv", "cache", "prune"],
            "uv cache prune",
            dry_run=False,
        )

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command")
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_tool_cleanup_stops_when_reported_path_is_unsafe(
        self,
        mock_query,
        mock_inventory,
        mock_cleanup,
    ):
        mock_query.return_value = ("/var/cache/uv", "uv", None)
        mock_inventory.return_value = (None, None)

        failures = user_cache_maintenance.cleanup_uv_cache(
            self.context,
            dry_run=False,
        )

        self.assertEqual(failures, [])
        mock_cleanup.assert_not_called()

    @patch("common.service_tools.user_cache_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.user_cache_maintenance.inventory_cache")
    @patch("common.service_tools.user_cache_maintenance.query_cache_path")
    def test_go_cache_cleans_only_above_limit(self, mock_query, mock_inventory, mock_cleanup):
        mock_query.return_value = ("/home/agent/.cache/go-build", "go", None)
        mock_inventory.return_value = (
            user_cache_maintenance.CacheUsage(101, time.time()),
            None,
        )

        failures = user_cache_maintenance.cleanup_go_cache(
            self.context,
            cache_name="Go build cache",
            go_env_name="GOCACHE",
            max_bytes=100,
            clean_args=["-cache", "-testcache", "-fuzzcache"],
            dry_run=False,
        )

        self.assertEqual(failures, [])
        mock_cleanup.assert_called_once_with(
            self.context,
            ["go", "clean", "-cache", "-testcache", "-fuzzcache"],
            "Go build cache oversized cleanup",
            dry_run=False,
        )

    @patch("common.service_tools.user_cache_maintenance.cleanup_stale_children", return_value=[])
    @patch("common.service_tools.user_cache_maintenance.cleanup_managed_directory", return_value=[])
    def test_agent_cache_policy_never_targets_persistent_state(
        self,
        mock_directory_cleanup,
        mock_stale_cleanup,
    ):
        with patch.dict(os.environ, {}, clear=True):
            user_cache_maintenance.cleanup_agent_caches(self.context, dry_run=False)

        managed_paths = [call.kwargs["path"] for call in mock_directory_cleanup.call_args_list]
        self.assertEqual(
            managed_paths,
            ["/home/agent/.cache/opencode", "/home/agent/.codex/cache"],
        )
        self.assertEqual(
            mock_stale_cleanup.call_args.kwargs["path"],
            "/home/agent/.codex/tmp",
        )
        self.assertFalse(any(".local/share/opencode" in path for path in managed_paths))


class TestUserCacheMain(unittest.TestCase):
    @patch("common.service_tools.user_cache_maintenance.run_user_cache_maintenance")
    @patch("common.service_tools.user_cache_maintenance.resolve_user_context")
    def test_dry_run_is_forwarded_to_cache_policies(self, mock_context, mock_run):
        context = user_cache_maintenance.UserContext("agent", "/home/agent", 1000)
        mock_context.return_value = context
        mock_run.return_value = []

        result = user_cache_maintenance.main(["--dry-run"])

        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(context, dry_run=True)

    @patch("common.service_tools.user_cache_maintenance.run_user_cache_maintenance")
    @patch("common.service_tools.user_cache_maintenance.resolve_user_context")
    def test_root_account_is_skipped(self, mock_context, mock_run):
        mock_context.return_value = user_cache_maintenance.UserContext("root", "/root", 0)

        result = user_cache_maintenance.main([])

        self.assertEqual(result, 0)
        mock_run.assert_not_called()

    @patch("common.service_tools.user_cache_maintenance.run_user_cache_maintenance")
    @patch("common.service_tools.user_cache_maintenance.resolve_user_context")
    def test_failures_return_nonzero(self, mock_context, mock_run):
        mock_context.return_value = user_cache_maintenance.UserContext(
            "agent",
            "/home/agent",
            1000,
        )
        mock_run.return_value = ["npm cache: failed"]

        result = user_cache_maintenance.main([])

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
