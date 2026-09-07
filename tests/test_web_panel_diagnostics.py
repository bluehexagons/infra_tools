"""Tests for bounded, on-demand journal and runtime inspection."""

from __future__ import annotations

import json
import unittest
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from common.service_tools import web_panel_diagnostics as diagnostics
from common.service_tools import web_panel_service as panel


class DiagnosticQueryTest(unittest.TestCase):
    def test_opening_form_does_not_collect(self) -> None:
        query = diagnostics.parse_query("service=homebox.service")
        with patch.object(diagnostics, "collect_diagnostics") as collect:
            page = diagnostics.render_diagnostics(query, "", "host<name>")
        collect.assert_not_called()
        self.assertIn("No log query has run yet", page)
        self.assertIn('value="homebox.service" selected', page)
        self.assertIn("host&lt;name&gt;", page)

    def test_rejects_unbounded_or_ambiguous_filters(self) -> None:
        for raw in (
            "service=../../etc/shadow", "service=nginx*", "service=--all",
            "service=ssh.service&service=nginx.service", "window=100years",
            "priority=8", "load=0", "load=", "file=/etc/passwd",
            "search=a&search=b", "search=%00", "search=" + "x" * 121,
            "window=1h&priority=3&load=1&service=ssh.service&extra=1", "x" * 2049,
        ):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                diagnostics.parse_query(raw)

    def test_journal_filters_are_fixed_and_user_scoped(self) -> None:
        query = diagnostics.parse_query("service=t3code.service&window=boot&priority=3&load=1")
        record = {"MESSAGE": "Start failed <script>", "PRIORITY": "3", "__REALTIME_TIMESTAMP": "1000000"}
        with patch.object(diagnostics, "_bounded_command", side_effect=[
            ("LoadState=loaded\nNRestarts=3\nExecStart=secret\n", ""),
            (json.dumps(record), ""),
        ]) as run:
            result = diagnostics.collect_diagnostics(query)
        command = run.call_args.args[0]
        self.assertIn("--user", command)
        self.assertIn("--unit=t3code.service", command)
        self.assertIn("--boot=0", command)
        self.assertIn("--priority=3", command)
        self.assertIn("--lines=100", command)
        self.assertNotIn("ExecStart", result["properties"])
        self.assertEqual(result["events"][0]["timestamp"], "1970-01-01T00:00:01+00:00")

    def test_message_search_is_literal_and_applied_before_entry_limit(self) -> None:
        query = diagnostics.parse_query("search=failed%5B1%5D.*&load=1")
        with patch.object(diagnostics, "_bounded_command", return_value=("", "")) as run:
            diagnostics.collect_diagnostics(query)
        command = run.call_args.args[0]
        self.assertIn(r"--grep=failed\[1\]\.\*", command)
        self.assertIn("--case-sensitive=no", command)

    def test_result_never_renders_more_than_100_events(self) -> None:
        journal = "\n".join(json.dumps({"MESSAGE": str(i)}) for i in range(120))
        with patch.object(diagnostics, "_bounded_command", side_effect=[("LoadState=loaded", ""), (journal, "")]):
            result = diagnostics.collect_diagnostics(diagnostics.DiagnosticQuery(load=True))
        self.assertEqual(len(result["events"]), 100)

    def test_system_scope_and_incomplete_journal_are_visible(self) -> None:
        with patch.object(diagnostics, "_bounded_command", side_effect=[
            ("LoadState=not-found", ""),
            ('Hint: You are currently not seeing messages from other users.\n' +
             json.dumps({"MESSAGE": [65, 66], "__REALTIME_TIMESTAMP": "bad"}) + '\n{"MESSAGE":', "Output limit reached"),
        ]) as run:
            result = diagnostics.collect_diagnostics(diagnostics.DiagnosticQuery(load=True))
        self.assertIn("--system", run.call_args.args[0])
        self.assertIn("--since=-1h", run.call_args.args[0])
        self.assertEqual(len(result["issues"]), 2)
        self.assertIn("omitted", result["events"][0]["message"])
        self.assertEqual(result["events"][0]["timestamp"], "Unknown time")

    def test_busy_collectors_do_not_start_processes(self) -> None:
        with (
            patch.object(diagnostics, "_COLLECTORS") as semaphore,
            patch.object(diagnostics, "_bounded_command") as run,
        ):
            semaphore.acquire.return_value = False
            result = diagnostics.collect_diagnostics(diagnostics.DiagnosticQuery(load=True))
        run.assert_not_called()
        self.assertIn("busy", result["issues"][0])

    def test_render_escapes_messages_and_explains_empty_results(self) -> None:
        result = {"issues": ["Incomplete <journal>"], "properties": {"MemoryCurrent": "1048576"},
                  "events": [{"message": "<script>alert(1)</script>", "timestamp": "now", "priority": "3"}]}
        with patch.object(diagnostics, "collect_diagnostics", return_value=result):
            page = diagnostics.render_diagnostics(diagnostics.DiagnosticQuery(load=True), "", "host")
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("1.0 MiB", page)
        self.assertIn("Incomplete &lt;journal&gt;", page)
        result["events"] = []
        with patch.object(diagnostics, "collect_diagnostics", return_value=result):
            page = diagnostics.render_diagnostics(diagnostics.DiagnosticQuery(load=True), "", "host")
        self.assertIn("No matching entries are visible", page)

    def test_handler_rejects_bad_filters_before_collection(self) -> None:
        handler = object.__new__(panel.WebPanelHandler)
        handler.path = "/logs?service=--all&load=1"
        handler._send = Mock()
        with patch.object(panel, "render_diagnostics") as render:
            handler.do_GET()
        render.assert_not_called()
        self.assertEqual(handler._send.call_args.args[0], HTTPStatus.BAD_REQUEST)

    def test_handler_serves_form_without_dashboard_discovery(self) -> None:
        handler = object.__new__(panel.WebPanelHandler)
        handler.path = "/logs"
        handler.state = SimpleNamespace(manifest={"host": "host"})
        handler._send = Mock()
        with (
            patch.object(panel, "render_page") as dashboard,
            patch.object(diagnostics, "_bounded_command") as command,
        ):
            handler.do_GET()
        dashboard.assert_not_called()
        command.assert_not_called()
        self.assertEqual(handler._send.call_args.args[0], HTTPStatus.OK)


class BoundedCommandTest(unittest.TestCase):
    def _run(
        self, chunks: list[bytes], *, ready: bool = True, returncode: int = 0,
        command: list[str] | None = None,
    ) -> tuple[str, str, MagicMock]:
        process = MagicMock()
        process.__enter__.return_value = process
        process.wait.return_value = returncode
        process.poll.return_value = None
        selector = MagicMock()
        selector.__enter__.return_value = selector
        selector.select.return_value = [True] if ready else []
        with (
            patch.object(diagnostics.subprocess, "Popen", return_value=process),
            patch.object(diagnostics.selectors, "DefaultSelector", return_value=selector),
            patch.object(diagnostics.os, "read", side_effect=chunks),
            patch.object(diagnostics, "_MAX_BYTES", 8),
        ):
            output, issue = diagnostics._bounded_command(command or ["journalctl", "--no-pager"])
        return output, issue, process

    def test_small_output_is_returned(self) -> None:
        output, issue, process = self._run([b"hello", b""])
        self.assertEqual((output, issue), ("hello", ""))
        process.wait.assert_called()

    def test_output_cap_kills_and_reaps_process(self) -> None:
        output, issue, process = self._run([b"123456789"])
        self.assertEqual(output, "12345678")
        self.assertIn("Output limit", issue)
        process.kill.assert_called_once()
        process.wait.assert_called()

    def test_timeout_kills_and_reaps_process(self) -> None:
        output, issue, process = self._run([], ready=False)
        self.assertEqual(output, "")
        self.assertIn("timed out", issue)
        process.kill.assert_called_once()
        process.wait.assert_called()

    def test_missing_command_is_reported(self) -> None:
        with patch.object(diagnostics.subprocess, "Popen", side_effect=FileNotFoundError):
            output, issue = diagnostics._bounded_command(["journalctl"])
        self.assertEqual(output, "")
        self.assertIn("unavailable", issue)

    def test_no_search_matches_is_not_a_command_failure(self) -> None:
        output, issue, _ = self._run([b""], returncode=1, command=["journalctl", "--grep=missing"])
        self.assertEqual((output, issue), ("", ""))
        _, issue, _ = self._run([b""], returncode=1)
        self.assertIn("unavailable", issue)


if __name__ == "__main__":
    unittest.main()
