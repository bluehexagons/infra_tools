"""CLI for shared desktop lifecycle and bounded native application control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from desktop import session_runtime as runtime


def add_desktop_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("desktop", help="Start and use the shared desktop as its owner")
    commands = parser.add_subparsers(dest="desktop_command", required=True)
    for name in ("status", "start", "logout"):
        commands.add_parser(name).add_argument("--json", action="store_true")
    screenshot = commands.add_parser("screenshot")
    screenshot.add_argument("--output", required=True)
    screenshot.add_argument("--json", action="store_true")
    execute = commands.add_parser("exec")
    execute.add_argument("argv", nargs=argparse.REMAINDER)
    control = commands.add_parser("control")
    control.add_argument("operation", choices=("pause", "resume"))
    action = commands.add_parser("input", help="Apply a bounded input using screenshot generation/geometry")
    action.add_argument("--generation", required=True)
    action.add_argument("--geometry", required=True, nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    action.add_argument("kind", choices=("key", "text", "click", "move"))
    action.add_argument("--key")
    action.add_argument("--text")
    action.add_argument("--x", type=int)
    action.add_argument("--y", type=int)
    action.add_argument("--button", type=int, default=1)


def run_desktop_command(args: argparse.Namespace) -> int:
    try:
        command = args.desktop_command
        if command == "status":
            result = runtime.status()
        elif command == "start":
            result = runtime.start()
        elif command == "control":
            result = runtime.request({"action": args.operation})
        else:
            current = runtime.status()
            if current["state"] != "running":
                raise RuntimeError("Desktop is stopped; run 'infra-tools desktop start' first")
            payload = {"action": command, "generation": current["generation"]}
            if command == "screenshot":
                payload["output"] = str(Path(args.output).absolute())
                result = runtime.request(payload)
            else:
                if command == "exec":
                    payload["argv"] = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
                elif command == "input":
                    payload.update({name: getattr(args, name) for name in ("generation", "geometry", "kind", "key", "text", "x", "y", "button")})
                lease = runtime.request({"action": "acquire", "generation": payload["generation"]})
                payload["lease"] = lease["lease"]
                try:
                    result = runtime.request(payload)
                finally:
                    try:
                        runtime.request({"action": "release", "generation": payload["generation"], "lease": lease["lease"]})
                    except (OSError, RuntimeError):
                        pass  # Logout or human takeover may have revoked the lease.
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
