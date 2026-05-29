"""Tests for uv installer validation in common/common_steps.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import common_steps
from common.common_steps import _validate_uv_install_script


class TestValidateUvInstallScript(unittest.TestCase):
    def _create_temp_script(self, content: str, mode: int = 0o644) -> str:
        """Create a temporary script file with given content and permissions."""
        fd, path = tempfile.mkstemp(suffix='.sh')
        os.close(fd)
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, mode)
        return path

    def test_valid_uv_install_script(self):
        content = """#!/bin/sh
set -e
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertTrue(result)
            finally:
                os.unlink(f.name)

    def test_valid_uv_install_script_github_url(self):
        content = """#!/usr/bin/env sh
# Installer for uv from github.com/astral-sh/uv
curl -LsSf https://github.com/astral-sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertTrue(result)
            finally:
                os.unlink(f.name)

    def test_missing_shebang(self):
        content = """set -e
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_missing_uv_reference(self):
        content = """#!/bin/sh
set -e
curl -LsSf https://example.com/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_suspicious_rm_rf(self):
        content = """#!/bin/sh
rm -rf / some_file
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_suspicious_chmod_777(self):
        content = """#!/bin/sh
chmod -R 777 /etc
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_suspicious_mkfs(self):
        content = """#!/bin/sh
mkfs.ext4 /dev/sda
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_suspicious_dd_if(self):
        content = """#!/bin/sh
dd if=/dev/zero of=/dev/sda
curl -LsSf https://astral.sh/uv/install.sh | sh
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_nonexistent_file(self):
        result = _validate_uv_install_script('/nonexistent/path/script.sh')
        self.assertFalse(result)

    def test_file_with_only_whitespace(self):
        content = """   
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(content)
            f.flush()
            os.chmod(f.name, 0o644)
            try:
                result = _validate_uv_install_script(f.name)
                self.assertFalse(result)
            finally:
                os.unlink(f.name)


class TestInstallOrUpdateUv(unittest.TestCase):
    @patch("common.common_steps.os.path.exists")
    @patch("common.common_steps.run")
    def test_user_uv_update_repairs_ownership_and_sets_login_env(self, mock_run, mock_exists):
        def exists(path: str) -> bool:
            return path in {
                "/home/user/.local",
                "/home/user/.local/bin/uv",
                "/home/user/.cache",
            }

        mock_exists.side_effect = exists
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

        result = common_steps.install_or_update_uv("/home/user", username="user")

        self.assertTrue(result)
        commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("chown -R user:user /home/user/.local", commands)
        self.assertIn("chown -R user:user /home/user/.cache", commands)
        self.assertTrue(
            any(
                "HOME=/home/user USER=user LOGNAME=user" in command
                and "/home/user/.local/bin/uv self update" in command
                for command in commands
            )
        )


if __name__ == '__main__':
    unittest.main()
