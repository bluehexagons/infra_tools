"""Tests for versioned durable operation markers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from lib.operation_state import OperationStateError, OperationStateStore


class TestOperationStateStore(unittest.TestCase):
    def test_lifecycle_is_persistent_and_completed_marker_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "operation.json")
            store = OperationStateStore(path)
            started = store.begin(
                "manifest_deploy",
                "/var/www/example",
                "preparing",
                context={"release": "previous"},
            )

            self.assertEqual(store.load(), started)
            activating = store.transition(started.operation_id, "activating")
            self.assertEqual(activating.phase, "activating")
            self.assertEqual(activating.context, {"release": "previous"})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

            store.complete(started.operation_id)
            self.assertIsNone(store.load())

    def test_existing_marker_blocks_new_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = OperationStateStore(os.path.join(tmpdir, "operation.json"))
            started = store.begin("setup", "host", "applying")

            with self.assertRaisesRegex(OperationStateError, started.operation_id):
                store.begin("setup", "host", "applying")

    def test_recovery_required_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = OperationStateStore(os.path.join(tmpdir, "operation.json"))
            started = store.begin("manifest_deploy", "app", "activating")

            failed = store.transition(
                started.operation_id,
                "recovery",
                status="recovery_required",
                context={"reason": "service restart failed"},
            )

            self.assertEqual(store.load(), failed)
            self.assertEqual(failed.status, "recovery_required")

    def test_corrupt_marker_names_path_and_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "operation.json")
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write("{broken")
            store = OperationStateStore(path)

            with self.assertRaisesRegex(OperationStateError, path):
                store.begin("setup", "host", "applying")

            with open(path, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "{broken")

    def test_unsupported_schema_has_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "operation.json")
            with open(path, "w", encoding="utf-8") as file_obj:
                json.dump({"schema_version": 99}, file_obj)

            with self.assertRaisesRegex(OperationStateError, "move the marker aside"):
                OperationStateStore(path).load()

    def test_symlink_marker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "target.json")
            marker = os.path.join(tmpdir, "operation.json")
            with open(target, "w", encoding="utf-8") as file_obj:
                file_obj.write("{}")
            os.symlink(target, marker)

            with self.assertRaisesRegex(OperationStateError, "must not be a symlink"):
                OperationStateStore(marker).load()

    def test_stale_operation_id_cannot_update_or_remove_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = OperationStateStore(os.path.join(tmpdir, "operation.json"))
            store.begin("setup", "host", "applying")

            for action in (
                lambda: store.transition("wrong-id", "verifying"),
                lambda: store.complete("wrong-id"),
            ):
                with self.subTest(action=action):
                    with self.assertRaisesRegex(OperationStateError, "wrong-id"):
                        action()

    def test_rejects_empty_labels_and_unknown_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = OperationStateStore(os.path.join(tmpdir, "operation.json"))
            with self.assertRaisesRegex(ValueError, "non-empty"):
                store.begin("", "host", "applying")
            started = store.begin("setup", "host", "applying")
            with self.assertRaisesRegex(ValueError, "Unsupported operation status"):
                store.transition(started.operation_id, "failed", status="failed")


if __name__ == "__main__":
    unittest.main()
