"""Regression tests for sync/service_tools/scrub_par2 verify_repair semantics
and sync/scrub_steps initial-par2 rollback.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sync.service_tools import scrub_par2


class TestVerifyRepairOutcomes(unittest.TestCase):
    """verify_repair must distinguish "repair failed" from "no problem"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = self.tmp.name
        self.database = os.path.join(self.tmp.name, '.par2db')
        os.makedirs(self.database, exist_ok=True)
        self.file_path = os.path.join(self.directory, 'data.bin')
        with open(self.file_path, 'wb') as fh:
            fh.write(b'hello world')
        # Create a stub par2 file so verify_repair runs the verify branch.
        par2_base = os.path.join(self.database, 'data.bin.par2')
        with open(par2_base, 'wb') as fh:
            fh.write(b'')
        self.log_file = os.path.join(self.tmp.name, 'scrub.log')

    def test_no_par2_returns_ok(self):
        os.remove(os.path.join(self.database, 'data.bin.par2'))
        result = scrub_par2.verify_repair(self.file_path, self.directory, self.database, self.log_file)
        self.assertEqual(result, scrub_par2.VERIFY_OK)

    @patch('sync.service_tools.scrub_par2.subprocess.run')
    def test_verification_passes_returns_ok(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
        result = scrub_par2.verify_repair(self.file_path, self.directory, self.database, self.log_file)
        self.assertEqual(result, scrub_par2.VERIFY_OK)

    @patch('sync.service_tools.scrub_par2.subprocess.run')
    def test_repair_succeeds_returns_repaired(self, mock_run):
        # First call (verify) raises, second call (repair) succeeds.
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'par2 verify', output='corrupted'),
            subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr=''),
        ]
        result = scrub_par2.verify_repair(self.file_path, self.directory, self.database, self.log_file)
        self.assertEqual(result, scrub_par2.VERIFY_REPAIRED)

    @patch('sync.service_tools.scrub_par2.subprocess.run')
    def test_repair_fails_returns_unrepairable(self, mock_run):
        # Both verify and repair raise.
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'par2 verify', output='corrupted'),
            subprocess.CalledProcessError(1, 'par2 repair', output='unrecoverable'),
        ]
        result = scrub_par2.verify_repair(self.file_path, self.directory, self.database, self.log_file)
        self.assertEqual(result, scrub_par2.VERIFY_UNREPAIRABLE)


class TestRollbackInitialPar2(unittest.TestCase):
    """rollback_initial_par2 must clean the database directory tree, not the
    protected directory (par2 files are written into ``database_path``)."""

    def test_remove_par2_files_under_walks_tree(self):
        from sync.scrub_steps import remove_par2_files_under

        with tempfile.TemporaryDirectory() as tmp:
            directory = os.path.join(tmp, 'data')
            database = os.path.join(tmp, 'pardb')
            os.makedirs(os.path.join(database, 'sub'))
            os.makedirs(directory)

            par2_top = os.path.join(database, 'a.par2')
            par2_nested = os.path.join(database, 'sub', 'b.vol00+01.par2')
            for path in (par2_top, par2_nested):
                with open(path, 'wb') as fh:
                    fh.write(b'')

            unrelated = os.path.join(directory, 'keep.txt')
            with open(unrelated, 'w') as fh:
                fh.write('keep me')

            removed = remove_par2_files_under(database)

            self.assertEqual(sorted(removed), sorted([par2_top, par2_nested]))
            self.assertFalse(os.path.exists(par2_top))
            self.assertFalse(os.path.exists(par2_nested))
            self.assertTrue(os.path.exists(unrelated))

    def test_remove_par2_files_under_missing_dir(self):
        from sync.scrub_steps import remove_par2_files_under
        self.assertEqual(remove_par2_files_under('/nonexistent/path/xyz'), [])


if __name__ == '__main__':
    unittest.main()
