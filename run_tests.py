#!/usr/bin/env python3
"""Test runner for infra_tools.

By default, expensive tests (live Proxmox round-trips, network downloads, etc.)
are skipped. Opt in with ``--expensive CATEGORY`` (repeatable) or
``--expensive all``.

Examples:
    ./run_tests.py                                  # full default suite, concise output
    ./run_tests.py -v                               # verbose
    ./run_tests.py test_proxmox_manage              # one test module
    ./run_tests.py tests.test_proxmox_manage.TestHealthCheck   # one class
    ./run_tests.py --list-categories                # show known expensive categories
    ./run_tests.py --expensive live_proxmox \
        tests.test_proxmox_live                     # run a real Proxmox round-trip
    ./run_tests.py --expensive all                  # run everything including expensive

Selectors are matched case-insensitively against test module file names; you
can also pass a fully-qualified ``tests.module.Class.method`` selector and it
will be loaded directly.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import unittest
from pathlib import Path
from typing import TextIO

# Make `tests/` importable when running from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from tests.expensive_support import (  # noqa: E402  (after sys.path tweak)
    EXPENSIVE_ENV_VAR,
    KNOWN_CATEGORIES,
    category_env_var,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the infra_tools test suite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "selectors",
        nargs="*",
        help=(
            "Optional test selectors: file stems (test_proxmox_manage), "
            "module dotted paths (tests.test_proxmox_manage), or fully "
            "qualified test ids."
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose test output (does not suppress infra_tools console logs).",
    )
    parser.add_argument(
        "--expensive",
        action="append",
        metavar="CATEGORY",
        default=[],
        help=(
            "Enable an expensive test category. Repeatable. "
            "Use 'all' to enable every expensive test."
        ),
    )
    parser.add_argument(
        "--list-categories", action="store_true",
        help="List the known expensive-test categories and exit.",
    )
    parser.add_argument(
        "--list-tests", action="store_true",
        help="List the discovered test files and exit.",
    )
    return parser


def _list_categories() -> int:
    print("Known expensive-test categories:")
    print()
    width = max(len(c) for c in KNOWN_CATEGORIES) if KNOWN_CATEGORIES else 0
    for name, desc in sorted(KNOWN_CATEGORIES.items()):
        env = category_env_var(name)
        print(f"  {name:<{width}}  {desc}")
        print(f"  {'':<{width}}    enable: {env}=1  (or --expensive {name})")
    print()
    print(f"Or set {EXPENSIVE_ENV_VAR}=1 (--expensive all) to enable everything.")
    return 0


def _list_tests() -> int:
    test_dir = _REPO_ROOT / "tests"
    print("Discovered test files:")
    for test_file in sorted(test_dir.rglob("test_*.py")):
        rel_path = test_file.relative_to(test_dir)
        print(f"  {rel_path}")
    return 0


def _apply_expensive_flags(categories: list[str]) -> list[str]:
    """Set the env vars that gate expensive tests. Returns the categories enabled."""
    enabled: list[str] = []
    for raw in categories:
        cat = raw.strip().lower()
        if not cat:
            continue
        if cat == "all":
            os.environ[EXPENSIVE_ENV_VAR] = "1"
            enabled.append("all")
            continue
        os.environ[category_env_var(cat)] = "1"
        enabled.append(cat)
    return enabled


def _resolve_selector(loader: unittest.TestLoader, selector: str):
    """Resolve a single selector to a test suite.

    Accepted forms:
      * file stem:           "test_proxmox_manage" or "test_proxmox_manage.py"
      * dotted module:       "tests.test_proxmox_manage"
      * dotted test id:      "tests.test_proxmox_manage.TestHealthCheck.test_x"
      * bare class/method:   tries "tests.<selector>" as a fallback
    """
    candidates: list[str] = []
    s = selector
    if s.endswith(".py"):
        s = s[:-3]
    if "/" in s or os.sep in s:
        s = s.replace("/", ".").replace(os.sep, ".")

    if s.startswith("tests."):
        candidates.append(s)
    else:
        # Try direct module under tests/ (file stem like "test_foo").
        test_dir = _REPO_ROOT / "tests"
        matches = list(test_dir.rglob(f"{s}.py"))
        for match in matches:
            rel = match.relative_to(test_dir).with_suffix("")
            candidates.append("tests." + str(rel).replace(os.sep, "."))
        # Also try the selector as-is, in case it's a class.method.
        candidates.append(f"tests.{s}")
        candidates.append(s)

    last_error: Exception | None = None
    for name in candidates:
        try:
            return loader.loadTestsFromName(name)
        except (ImportError, AttributeError) as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"Could not resolve test selector {selector!r}. Tried: {candidates}. "
        f"Last error: {last_error}"
    )


def _build_suite(loader: unittest.TestLoader, selectors: list[str]) -> unittest.TestSuite:
    if not selectors:
        return loader.discover("tests", pattern="test_*.py")
    suite = unittest.TestSuite()
    for sel in selectors:
        suite.addTests(_resolve_selector(loader, sel))
    return suite


class _Tee:
    """Tee writes to capture (always) and the original stream (optional)."""

    def __init__(self, original: TextIO, capture: io.StringIO, passthrough: bool) -> None:
        self.original = original
        self.capture = capture
        self.passthrough = passthrough

    def write(self, data: str) -> int:
        self.capture.write(data)
        if self.passthrough:
            return self.original.write(data)
        return len(data)

    def flush(self) -> None:
        if self.passthrough:
            self.original.flush()

    def isatty(self) -> bool:  # pragma: no cover - cosmetic
        return self.original.isatty()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_categories:
        return _list_categories()
    if args.list_tests:
        return _list_tests()

    enabled = _apply_expensive_flags(args.expensive)
    if enabled:
        print(f"Expensive categories enabled: {', '.join(enabled)}")

    if not args.verbose:
        os.environ.setdefault("INFRA_TOOLS_TEST", "1")

    os.chdir(_REPO_ROOT)

    loader = unittest.TestLoader()
    try:
        suite = _build_suite(loader, args.selectors)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.verbose:
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
    else:
        capture = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = capture
        sys.stderr = capture
        try:
            runner = unittest.TextTestRunner(stream=capture, verbosity=0)
            result = runner.run(suite)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        if not result.wasSuccessful():
            sys.stdout.write(capture.getvalue())

    print()
    skipped = len(result.skipped)
    if result.wasSuccessful():
        msg = f"✓ All tests passed ({result.testsRun} run"
        if skipped:
            msg += f", {skipped} skipped"
        msg += ")"
        print(msg)
        return 0
    print(
        f"✗ Tests failed: {len(result.failures)} failures, "
        f"{len(result.errors)} errors, {skipped} skipped"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
