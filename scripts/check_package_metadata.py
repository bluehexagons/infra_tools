#!/usr/bin/env python3
"""Check the installable package's launcher metadata and public command name."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with (ROOT / "pyproject.toml").open("rb") as file_obj:
        project = tomllib.load(file_obj)["project"]
    scripts = project.get("scripts", {})
    if scripts.get("infra-tools") != "infra_tools:main":
        print("pyproject.toml must expose infra_tools:main as the infra-tools entry point")
        return 1
    if "infra_tools" in scripts:
        print("pyproject.toml must not restore the retired infra_tools launcher")
        return 1
    command_reference = (ROOT / "docs" / "COMMAND_LINE.md").read_text(encoding="utf-8")
    if "infra-tools setup" not in command_reference:
        print("docs/COMMAND_LINE.md must document the infra-tools launcher")
        return 1
    print("Package metadata check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
