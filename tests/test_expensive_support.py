"""Tests for tests/expensive_support.py: ensure the gate honours the env flag."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.expensive_support import EXPENSIVE_ENV_VAR, expensive_tests_enabled


class TestExpensiveSupport(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with _env_unset(EXPENSIVE_ENV_VAR):
            self.assertFalse(expensive_tests_enabled())

    def test_enabled_when_truthy(self) -> None:
        for value in ("1", "true", "yes", "on", "TRUE", "On"):
            with _env_set(EXPENSIVE_ENV_VAR, value):
                self.assertTrue(expensive_tests_enabled(), f"value={value!r}")

    def test_disabled_when_falsy(self) -> None:
        for value in ("0", "false", "no", "off", ""):
            with _env_set(EXPENSIVE_ENV_VAR, value):
                self.assertFalse(expensive_tests_enabled(), f"value={value!r}")


class _env_set:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value
        self._previous: object = None

    def __enter__(self) -> None:
        self._previous = os.environ.get(self.key)
        os.environ[self.key] = self.value

    def __exit__(self, *exc) -> None:
        if self._previous is None:
            os.environ.pop(self.key, None)
        else:
            os.environ[self.key] = str(self._previous)


class _env_unset:
    def __init__(self, key: str) -> None:
        self.key = key
        self._previous: object = None

    def __enter__(self) -> None:
        self._previous = os.environ.get(self.key)
        os.environ.pop(self.key, None)

    def __exit__(self, *exc) -> None:
        if self._previous is not None:
            os.environ[self.key] = str(self._previous)


if __name__ == "__main__":
    unittest.main()
