"""Tests for concise end-of-run setup notes."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from lib.setup_report import SetupReport, get_setup_report


class SetupReportTest(unittest.TestCase):
    def test_observes_and_deduplicates_marked_lines(self) -> None:
        report = SetupReport()
        report.set_step("Configure web")
        report.observe("  ⚠ certificate check was skipped")
        report.observe("  ⚠ certificate check was skipped")
        report.observe("  ✗ nginx reload failed")
        report.observe("normal progress output")

        self.assertEqual(len(report.notes), 2)
        self.assertEqual(report.notes[0].severity, "warning")
        self.assertEqual(report.notes[0].step, "Configure web")
        self.assertEqual(report.notes[1].severity, "error")
        self.assertNotIn("✗", report.notes[1].message)

    def test_capture_forwards_output_and_records_complete_lines(self) -> None:
        report = SetupReport()
        output = io.StringIO()
        with redirect_stdout(output):
            with report.capture():
                print("  ⚠ first half", end="")
                print(" of warning")

        self.assertIn("first half of warning", output.getvalue())
        self.assertEqual(len(report.notes), 1)
        self.assertIn("first half of warning", report.notes[0].message)

    def test_render_groups_notes_for_skimming(self) -> None:
        report = SetupReport()
        report.error("service failed", step="Web")
        report.warning("certificate is local", step="Web")
        output = io.StringIO()
        with redirect_stdout(output):
            report.render()

        rendered = output.getvalue()
        self.assertIn("Run notes:", rendered)
        self.assertIn("Errors (1):", rendered)
        self.assertIn("Warnings (1):", rendered)
        self.assertLess(rendered.index("Errors"), rendered.index("Warnings"))

    def test_active_report_is_scoped(self) -> None:
        self.assertIsNone(get_setup_report())
        report = SetupReport()
        with report.activate():
            self.assertIs(get_setup_report(), report)
        self.assertIsNone(get_setup_report())


if __name__ == "__main__":
    unittest.main()
