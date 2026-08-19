"""Interactive choices for agent VM setup."""

from __future__ import annotations

import getpass
import sys
from typing import Any

from lib.config import (
    AGENT_TOOLS,
    BROWSER_AUTOMATION_PROVIDERS,
    GIT_ACCESS_POLICIES,
)


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _prompt_choice(prompt: str, choices: tuple[str, ...], default: str) -> str:
    while True:
        value = _prompt(f"{prompt} ({'/'.join(choices)})", default).lower()
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


def _prompt_repositories() -> list[str]:
    repositories: list[str] = []
    print("Enter HTTPS repository URLs to clone on the VM; leave blank when finished.")
    while True:
        value = input("Repository URL: ").strip()
        if not value:
            return repositories
        repositories.append(value)


def run_interactive_setup(args: Any) -> None:
    """Fill agent setup choices into a parsed setup namespace.

    Credential values are held only in the namespace for the current setup and
    are removed before configuration persistence. Dry-runs deliberately skip
    all credential prompts and secret staging.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("--interactive requires a TTY")

    if not getattr(args, "agent_tools", None):
        raw_tools = _prompt("Agent tools, comma-separated", "").strip()
        selected = [tool.strip() for tool in raw_tools.split(",") if tool.strip()]
        unknown = [tool for tool in selected if tool not in AGENT_TOOLS]
        if unknown:
            raise ValueError(f"Unsupported agent tool: {', '.join(unknown)}")
        args.agent_tools = list(dict.fromkeys(selected)) or None

    if not getattr(args, "agent_repos", None):
        args.agent_repos = _prompt_repositories() or None

    selected_tools = set(args.agent_tools or [])
    compatible_browser_tools = selected_tools.intersection({"codex", "opencode"})
    if compatible_browser_tools and not getattr(args, "browser_automation", None):
        browser_choice = _prompt_choice(
            "Agent browser automation",
            ("none", *BROWSER_AUTOMATION_PROVIDERS),
            "none",
        )
        args.browser_automation = None if browser_choice == "none" else browser_choice

    if args.agent_repos or "gh" in selected_tools:
        args.git_host = _prompt("Git host", getattr(args, "git_host", "github.com"))
        args.git_access = _prompt_choice(
            "VM Git access",
            GIT_ACCESS_POLICIES,
            getattr(args, "git_access", "none"),
        )

    if getattr(args, "dry_run", False):
        print("Dry-run: skipping credential prompts and secret staging.")
        return

    if (
        "gh" in selected_tools
        and args.git_host == "github.com"
        and args.git_access != "none"
    ):
        auth_choice = _prompt_choice(
            "GitHub credential source",
            ("none", "active", "file", "token"),
            "none",
        )
        if auth_choice == "active":
            args.git_auth_source = "active"
        elif auth_choice == "file":
            args.git_auth_file = _prompt("GitHub hosts.yml or token file")
        elif auth_choice == "token":
            args.git_auth_token = getpass.getpass("GitHub token (hidden): ").strip()
    elif "gh" in selected_tools and args.git_access == "none":
        print("GitHub credentials skipped because VM Git access is none.")

    non_gh_tools = sorted(selected_tools.difference({"gh", "t3code"}))
    if non_gh_tools:
        agent_auth_choice = _prompt_choice(
            "Credential source for selected coding agents",
            ("none", "active", "files"),
            "none",
        )
        if agent_auth_choice == "active":
            args.agent_auth_source = "active"
        elif agent_auth_choice == "files":
            args.agent_auth_files = []
            for tool in non_gh_tools:
                path = _prompt(f"{tool} credential file (blank to skip)")
                if path:
                    args.agent_auth_files.append([tool, path])
            if not args.agent_auth_files:
                args.agent_auth_files = None

    if selected_tools:
        if _prompt_choice("Copy optional non-secret agent config", ("no", "active"), "no") == "active":
            args.agent_config_source = "active"

    print("Interactive agent setup choices recorded; credentials will not be saved in the setup command.")
