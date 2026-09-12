"""Accessibility behavior without a display, D-Bus, or system mutations."""

from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktop import accessibility as a11y, client, session_runtime as runtime
from lib.desktop_cli import add_desktop_subparser, run_desktop_command


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(
            Role=SimpleNamespace(PASSWORD_TEXT="password text"),
            StateType=SimpleNamespace(**{state.upper(): state for state in a11y.STATES}),
            Text=SimpleNamespace(get_text=lambda node, start, end: node.get_text(start, end)),
            Error=RuntimeError,
        )
        self.field = self.node("Editor", "text", text="hello")
        self.app = self.node("Geany", "application", children=[self.field])
        self.app.get_process_id.return_value = 42
        self.api.get_desktop = Mock(return_value=self.node("desktop", children=[self.app]))

    def node(self, name, role="panel", children=(), text=None):
        node = Mock()
        node.app.bus_name = ":1.42"
        node.path = "/accessible/" + name
        node.get_name.return_value = name
        node.get_role_name.return_value = role
        node.get_role.return_value = role
        node.get_state_set.return_value.contains.side_effect = lambda state: state in {
            "enabled", "sensitive", "showing", "editable"}
        node.is_action.return_value = False
        node.is_text.return_value = text is not None
        node.is_editable_text.return_value = True
        node.get_text_iface.return_value.get_character_count.return_value = len(text or "")
        node.get_text_iface.return_value.get_text.side_effect = lambda start, end: text[start:end]
        node.get_child_count.return_value = len(children)
        node.get_child_at_index.side_effect = lambda index: children[index]
        return node

    def inspect(self, **kwargs):
        return a11y.perform({"pid": 42, **kwargs}, self.api)

    def test_filtered_inspection_and_unicode_edit(self):
        row = self.inspect(role="text")["elements"][0]
        self.assertEqual(row["text"], "hello")
        result = self.inspect(role="text", operation="set-text", ref=row["ref"], text="café\n日本語")
        self.assertEqual(result["requested"], "set-text")
        self.field.get_editable_text_iface.return_value.set_text_contents.assert_called_once_with("café\n日本語")

    def test_renamed_or_replaced_element_never_receives_action(self):
        row = self.inspect(role="text")["elements"][0]
        self.field.path = "/replacement"
        with self.assertRaisesRegex(ValueError, "changed"):
            self.inspect(operation="set-text", ref=row["ref"], text="replacement")
        self.field.get_editable_text_iface.assert_not_called()

    def test_disabled_control_rejected(self):
        row = self.inspect(role="text")["elements"][0]
        self.field.get_state_set.return_value.contains.side_effect = lambda state: state == "showing"
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.inspect(operation="set-text", ref=row["ref"], text="replacement")
        self.field.get_editable_text_iface.assert_not_called()

    def test_ancestor_name_change_invalidates_descendant_reference(self):
        ref = self.inspect(role="text")["elements"][0]["ref"]
        self.app.get_name.return_value = "Another document"
        with self.assertRaisesRegex(ValueError, "changed"):
            self.inspect(operation="set-text", ref=ref, text="replacement")
        self.field.get_editable_text_iface.assert_not_called()

    def test_hidden_subtrees_are_not_read(self):
        self.field.get_state_set.return_value.contains.side_effect = lambda state: False
        result = self.inspect(role="text")
        self.assertEqual(result["elements"], [])
        self.assertFalse(result["truncated"])
        self.field.get_text_iface.assert_not_called()
        self.field.get_child_count.assert_not_called()

    def test_password_contents_and_descendants_are_not_read(self):
        self.field.get_role.return_value = "password text"
        row = self.inspect()["elements"][1]
        self.assertTrue(row["protected"])
        self.assertEqual(row["name"], "")
        self.assertNotIn("text", row)
        self.field.get_name.assert_not_called()
        self.field.get_text_iface.assert_not_called()
        self.field.get_child_count.assert_not_called()

    def test_partial_scan_and_long_text_are_explicit(self):
        with patch.object(a11y, "MAX_NODES", 1):
            result = self.inspect()
        self.assertTrue(result["truncated"])
        self.field.get_text_iface.return_value.get_character_count.return_value = 10000
        row = self.inspect(role="text")["elements"][0]
        self.assertTrue(row["text_truncated"])
        self.field.get_text_iface.return_value.get_text.assert_called_with(0, 256)

    def test_named_action_must_be_unique_and_report_acceptance(self):
        self.field.is_action.return_value = True
        action = self.field.get_action_iface.return_value
        action.get_n_actions.return_value = 1
        action.get_action_name.return_value = "activate"
        row = self.inspect(role="text")["elements"][0]
        with self.assertRaisesRegex(ValueError, "exact action"):
            self.inspect(operation="invoke", ref=row["ref"], action_name="guess")
        action.do_action.assert_not_called()
        action.do_action.return_value = False
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.inspect(operation="invoke", ref=row["ref"], action_name="activate")

    def test_invalid_input_precedes_application_lookup(self):
        for pid in (0, -1, True, "42"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                a11y.perform({"pid": pid}, self.api)
        self.api.get_desktop.assert_not_called()

    @patch.object(a11y.subprocess, "run", side_effect=subprocess.TimeoutExpired("helper", 8))
    def test_hung_application_is_bounded(self, run):
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            a11y.worker_request({"pid": 42})
        self.assertEqual(run.call_args.kwargs["timeout"], 8)


class SessionTests(unittest.TestCase):
    def setUp(self):
        process = Mock(pid=100)
        process.poll.return_value = None
        self.session = runtime.DesktopSession({"desktop": "xfce", "username": "agent"}, process)
        self.row = {"ref": "ref", "name": "Editor", "role": "text", "states": ["enabled"]}
        self.result = {"pid": 42, "elements": [self.row], "truncated": False}
        patcher = patch.object(a11y, "worker_request", return_value=self.result)
        self.worker = patcher.start()
        self.addCleanup(patcher.stop)

    def inspect(self):
        return self.session.handle({"action": "inspect", "generation": self.session.generation, "pid": 42})

    def test_observation_during_pause_and_actions_require_lease(self):
        self.session.paused = True
        self.assertEqual(self.inspect()["elements"], [self.row])
        payload = {"action": "element", "generation": self.session.generation, "ref": "ref", "operation": "focus"}
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.session.handle(payload)
        self.session.paused = False
        with self.assertRaisesRegex(ValueError, "lease"):
            self.session.handle(payload)
        self.assertEqual(self.worker.call_count, 1)

    def test_reference_is_bound_to_observation_and_consumed_even_on_failure(self):
        self.inspect()
        lease = self.session.handle({"action": "acquire", "generation": self.session.generation})
        self.worker.side_effect = RuntimeError("Application rejected")
        payload = {"action": "element", **lease, "ref": "ref", "operation": "focus", "pid": 999}
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.session.handle(payload)
        self.assertEqual(self.worker.call_args.args[0]["pid"], 42)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.session.handle(payload)

    def test_expired_reference_and_stale_generation_fail_before_worker(self):
        self.inspect()
        lease = self.session.handle({"action": "acquire", "generation": self.session.generation})
        self.session.elements["ref"]["observed_at"] -= 61
        with self.assertRaisesRegex(ValueError, "expired"):
            self.session.handle({"action": "element", **lease, "ref": "ref", "operation": "focus"})
        with self.assertRaisesRegex(ValueError, "session changed"):
            self.session.handle({"action": "inspect", "generation": "old", "pid": 42})
        self.assertEqual(self.worker.call_count, 1)


class WaitTests(unittest.TestCase):
    @patch.object(runtime, "request", return_value={"generation": "g", "elements": [
        {"ref": "editor", "states": ["focused"]}, {"ref": "search", "states": []}], "truncated": False})
    def test_state_disambiguates_editor_from_other_text_controls(self, request):
        result = client.wait_for_element("g", pid=42, role="text", state="focused")
        self.assertEqual([row["ref"] for row in result["elements"]], ["editor"])

    @patch.object(client.time, "sleep")
    @patch.object(runtime, "request", side_effect=[
        {"generation": "g", "elements": [], "truncated": True},
        {"generation": "g", "elements": [], "truncated": False}])
    def test_absence_requires_complete_scan_without_lease(self, request, sleep):
        result = client.wait_for_element("g", pid=42, name="Save", state="absent")
        self.assertNotIn("error", result)
        self.assertEqual([call.args[0]["action"] for call in request.call_args_list], ["inspect", "inspect"])

    @patch.object(client.time, "monotonic", side_effect=[0, 2])
    @patch.object(runtime, "request", return_value={"generation": "g", "elements": [{}, {}], "truncated": False})
    def test_ambiguous_timeout_preserves_observations(self, request, clock):
        result = client.wait_for_element("g", pid=42, name="Save", timeout=1)
        self.assertIn("Timed out", result["error"])
        self.assertEqual(len(result["elements"]), 2)

    @patch.object(client.time, "monotonic", side_effect=[0, 2])
    @patch.object(runtime, "request", return_value={"generation": "g", "elements": [
        {"states": [], "text": "prefix", "text_truncated": True}], "truncated": False})
    def test_text_prefix_is_not_complete_text(self, request, clock):
        result = client.wait_for_element("g", pid=42, role="text", text="prefix", timeout=1)
        self.assertIn("error", result)

    @patch.object(runtime, "status", return_value={"state": "running", "generation": "g"})
    @patch.object(runtime, "request", side_effect=[{"lease": "l"}, {"requested": "invoke"}, {}])
    def test_cli_routes_named_action_and_releases_lease(self, request, status):
        parser = argparse.ArgumentParser()
        add_desktop_subparser(parser.add_subparsers())
        args = parser.parse_args(["desktop", "element", "invoke", "--generation", "g", "--ref", "ref", "--action-name", "click"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_desktop_command(args), 0)
        self.assertEqual(request.call_args_list[1].args[0]["action_name"], "click")
        self.assertEqual(request.call_args.args[0]["action"], "release")
