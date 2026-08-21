#!/usr/bin/env python3
"""Adapt GitHub CLI auth discovery JSON for T3 Code without wrapping normal use."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


SOURCE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from lib.validation import validate_filesystem_path


_T3_DISCOVERY_ARGS = ("auth", "status", "--json", "hosts")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GitHub CLI with T3 Code auth-discovery compatibility",
        add_help=False,
    )
    parser.add_argument("--gh-binary", required=True)
    return parser


def _sanitize_discovery_output(output: str) -> str:
    """Remove null error fields that T3's current strict schema rejects."""

    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return output
    if not isinstance(payload, dict) or not isinstance(payload.get("hosts"), dict):
        return output

    changed = False
    for accounts in payload["hosts"].values():
        if not isinstance(accounts, list):
            continue
        for account in accounts:
            if isinstance(account, dict) and account.get("error", object()) is None:
                account.pop("error")
                changed = True
    if not changed:
        return output
    return json.dumps(payload, separators=(",", ":")) + (
        "\n" if output.endswith("\n") else ""
    )


def run(gh_binary: str, arguments: list[str]) -> int:
    """Run the real GitHub CLI, adapting only T3's exact discovery probe."""

    validate_filesystem_path(gh_binary, must_exist=True)
    if not os.path.isfile(gh_binary) or not os.access(gh_binary, os.X_OK):
        raise ValueError(f"GitHub CLI is not an executable file: {gh_binary}")

    if tuple(arguments) != _T3_DISCOVERY_ARGS:
        os.execv(gh_binary, [gh_binary, *arguments])
        raise RuntimeError("GitHub CLI passthrough unexpectedly returned")

    result = subprocess.run(
        [gh_binary, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    sys.stdout.write(_sanitize_discovery_output(result.stdout))
    sys.stderr.write(result.stderr)
    return result.returncode


def main() -> int:
    args, gh_arguments = _parser().parse_known_args()
    try:
        return run(args.gh_binary, gh_arguments)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"t3code-gh-shim: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
