"""Local agentic coding tool diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from typing import Optional

from lib.types import JSONDict, StrList


AGENT_DOCTOR_TOOLS = ("gh", "codex", "claude", "opencode", "t3code")
DEFAULT_DOCTOR_TOOLS = ("gh", "codex", "claude", "opencode")

_CREDENTIAL_PATHS = {
    "gh": ".config/gh/hosts.yml",
    "codex": ".codex/auth.json",
    "claude": ".claude/.credentials.json",
    "opencode": ".local/share/opencode/auth.json",
}


def add_agent_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add local agent-tool management commands."""
    parser = subparsers.add_parser(
        "agent",
        help="Inspect local agentic coding tools",
    )
    commands = parser.add_subparsers(dest="agent_command", help="Agent commands")
    doctor = commands.add_parser(
        "doctor",
        help="Check installed agent tools and local credential files",
    )
    doctor.add_argument(
        "--tool",
        dest="agent_doctor_tools",
        action="append",
        choices=AGENT_DOCTOR_TOOLS,
        help="Tool to require; repeat as needed (default: terminal suite)",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )


def _tool_path(tool: str, home: str) -> Optional[str]:
    search_path = os.pathsep.join(
        (
            os.path.join(home, ".local", "bin"),
            os.path.join(home, ".opencode", "bin"),
            os.environ.get("PATH", ""),
        )
    )
    return shutil.which(tool, path=search_path)


def _tool_version(tool: str, path: str) -> Optional[str]:
    if tool == "t3code":
        return None
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def inspect_agent_tools(tools: StrList, home: Optional[str] = None) -> list[JSONDict]:
    """Return non-secret installation and credential status for selected tools."""
    user_home = home or os.path.expanduser("~")
    results: list[JSONDict] = []
    for tool in tools:
        path = _tool_path(tool, user_home)
        credential_relative = _CREDENTIAL_PATHS.get(tool)
        result: JSONDict = {
            "tool": tool,
            "installed": path is not None,
            "path": path,
            "version": _tool_version(tool, path) if path else None,
            "credential": (
                os.path.exists(os.path.join(user_home, credential_relative))
                if credential_relative
                else None
            ),
        }
        results.append(result)
    return results


def run_agent_command(args: argparse.Namespace) -> int:
    """Run a local agent-tool command."""
    if args.agent_command != "doctor":
        print("Error: agent command required (doctor)")
        return 1

    selected = list(args.agent_doctor_tools or DEFAULT_DOCTOR_TOOLS)
    results = inspect_agent_tools(selected)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("Agent tool check")
        for result in results:
            tool = str(result["tool"])
            if not result["installed"]:
                print(f"  ✗ {tool}: not installed")
                continue
            version = result.get("version")
            detail = f" ({version})" if version else ""
            print(f"  ✓ {tool}: {result['path']}{detail}")
            credential = result.get("credential")
            if credential is True:
                print("      credentials: present")
            elif credential is False:
                print("      credentials: not found; run the tool to sign in")

    return 0 if all(bool(result["installed"]) for result in results) else 1
