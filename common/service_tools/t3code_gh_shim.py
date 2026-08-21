#!/usr/bin/env python3
"""Adapt GitHub CLI auth discovery JSON for T3 Code without wrapping normal use."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit


SOURCE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from lib.validation import validate_filesystem_path
from lib.validators import validate_github_login, validate_host


_T3_DISCOVERY_ARGS = ("auth", "status", "--json", "hosts")
_T3_REPOSITORY_JSON_FIELDS = "nameWithOwner,url,sshUrl"
_GITHUB_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GitHub CLI with T3 Code auth-discovery compatibility",
        add_help=False,
    )
    parser.add_argument("--gh-binary", required=True)
    return parser


def _resolve_login(gh_binary: str, host: str) -> str | None:
    """Resolve the account name for an authenticated token-only hosts entry."""
    if not validate_host(host):
        return None
    try:
        result = subprocess.run(
            [gh_binary, "api", "user", "--hostname", host, "--jq", ".login"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    login = result.stdout.strip()
    if result.returncode != 0 or not validate_github_login(login):
        return None
    return login


def _repository_from_t3_arguments(arguments: list[str]) -> str | None:
    """Return the repository from T3's exact repository lookup command."""

    if (
        len(arguments) == 5
        and arguments[:2] == ["repo", "view"]
        and arguments[3:] == ["--json", _T3_REPOSITORY_JSON_FIELDS]
    ):
        return arguments[2]
    return None


def _canonical_repository(repository: str) -> dict[str, str] | None:
    """Build deterministic github.com clone URLs for a safe owner/repo name."""

    parts = repository.strip().split("/")
    if len(parts) != 2:
        return None
    owner, name = parts
    if (
        not validate_github_login(owner)
        or not _GITHUB_REPOSITORY_NAME_RE.fullmatch(name)
        or name in {".", ".."}
    ):
        return None
    name_with_owner = f"{owner}/{name}"
    return {
        "nameWithOwner": name_with_owner,
        "url": f"https://github.com/{name_with_owner}",
        "sshUrl": f"git@github.com:{name_with_owner}.git",
    }


def _parse_repository_output(output: str) -> dict[str, str] | None:
    """Read only the repository fields accepted by T3's strict schema."""

    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    normalized: dict[str, str] = {}
    for field in ("nameWithOwner", "url", "sshUrl"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            return None
        normalized[field] = value.strip()
    return normalized


def _preferred_git_protocol(gh_binary: str, repository_url: str) -> str | None:
    """Read the authenticated host's Git protocol without requiring a network call."""

    try:
        parsed = urlsplit(repository_url)
    except ValueError:
        return None
    host = parsed.hostname
    if not host or not validate_host(host):
        return None
    try:
        result = subprocess.run(
            [
                gh_binary,
                "config",
                "get",
                "git_protocol",
                "--host",
                host,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    protocol = result.stdout.strip().lower()
    if result.returncode != 0 or protocol not in {"https", "ssh"}:
        return None
    return protocol


def _repository_output_for_t3(
    output: str,
    repository: str,
    gh_binary: str,
) -> str | None:
    """Normalize lookup output and honor gh's configured clone protocol."""

    payload = _parse_repository_output(output) or _canonical_repository(repository)
    if payload is None:
        return None
    if _preferred_git_protocol(gh_binary, payload["url"]) == "https":
        # T3 0.0.33 always clones the field named sshUrl. Supplying the user's
        # configured HTTPS URL here keeps private clones on gh's credential
        # helper while remaining scoped to the T3-only launcher.
        payload["sshUrl"] = payload["url"]
    return json.dumps(payload, separators=(",", ":")) + "\n"


def _sanitize_discovery_output(output: str, gh_binary: str | None = None) -> str:
    """Normalize healthy GitHub records for T3's current strict schema."""

    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return output
    if not isinstance(payload, dict) or not isinstance(payload.get("hosts"), dict):
        return output

    changed = False
    resolved_logins: dict[str, str | None] = {}
    for configured_host, accounts in payload["hosts"].items():
        if not isinstance(accounts, list):
            continue
        for account in accounts:
            if not isinstance(account, dict):
                continue
            if account.get("error", object()) is None:
                account.pop("error")
                changed = True
            login = account.get("login")
            if (
                gh_binary
                and account.get("state") == "success"
                and (not isinstance(login, str) or not login.strip())
            ):
                account_host = account.get("host")
                host = (
                    account_host
                    if isinstance(account_host, str) and validate_host(account_host)
                    else configured_host
                )
                if not isinstance(host, str):
                    continue
                if host not in resolved_logins:
                    resolved_logins[host] = _resolve_login(gh_binary, host)
                resolved_login = resolved_logins[host]
                if resolved_login:
                    account["login"] = resolved_login
                    changed = True
    if not changed:
        return output
    return json.dumps(payload, separators=(",", ":")) + (
        "\n" if output.endswith("\n") else ""
    )


def run(gh_binary: str, arguments: list[str]) -> int:
    """Run GitHub CLI, adapting only T3's exact compatibility probes."""

    validate_filesystem_path(gh_binary, must_exist=True)
    if not os.path.isfile(gh_binary) or not os.access(gh_binary, os.X_OK):
        raise ValueError(f"GitHub CLI is not an executable file: {gh_binary}")

    repository = _repository_from_t3_arguments(arguments)
    if tuple(arguments) != _T3_DISCOVERY_ARGS and repository is None:
        os.execv(gh_binary, [gh_binary, *arguments])
        raise RuntimeError("GitHub CLI passthrough unexpectedly returned")

    result = subprocess.run(
        [gh_binary, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if repository is not None:
        normalized = _repository_output_for_t3(
            result.stdout,
            repository,
            gh_binary,
        )
        if normalized is not None:
            sys.stdout.write(normalized)
            return 0
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode

    sys.stdout.write(_sanitize_discovery_output(result.stdout, gh_binary))
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
