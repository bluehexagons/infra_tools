#!/usr/bin/env python3
"""Export one Godot project into the infra_tools HTTPS publishing root."""

from __future__ import annotations

import argparse
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile


GAMES_ROOT = "/srv/infra-tools/web/games"
BASE_URL_FILE = "/etc/infra-tools/internal-web/base-url"
_GAME_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a Godot project to its managed HTTPS web host",
    )
    parser.add_argument("game", help="URL-safe game name (lowercase letters, digits, - or _)")
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Godot project directory (default: current directory)",
    )
    parser.add_argument(
        "--preset",
        default="Web",
        help="Godot export preset name (default: Web)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Create a debug export instead of a release export",
    )
    return parser


def _validate_preset(value: str) -> str:
    if not value or len(value) > 128 or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("The export preset must be a short printable name")
    return value


def _current_account() -> pwd.struct_passwd:
    account = pwd.getpwuid(os.getuid())
    if account.pw_uid == 0:
        raise RuntimeError("Run godot-web-publish as the configured non-root user")
    return account


def _replace_export(staging_dir: str, destination_dir: str) -> None:
    """Activate a complete export while retaining the old one on failure."""

    parent_dir = os.path.dirname(destination_dir)
    if os.path.lexists(destination_dir) and (
        os.path.islink(destination_dir) or not os.path.isdir(destination_dir)
    ):
        raise RuntimeError(f"Refusing unsafe game destination: {destination_dir}")
    backup_dir = tempfile.mkdtemp(prefix=".previous-", dir=parent_dir)
    os.rmdir(backup_dir)
    previous_moved = False
    activated = False
    try:
        if os.path.isdir(destination_dir):
            os.replace(destination_dir, backup_dir)
            previous_moved = True
        os.replace(staging_dir, destination_dir)
        staging_dir = ""
        activated = True
    except Exception:
        if previous_moved and not os.path.exists(destination_dir):
            try:
                os.replace(backup_dir, destination_dir)
            except OSError as rollback_error:
                raise RuntimeError(
                    "Could not restore the previous export; it remains at "
                    f"{backup_dir}"
                ) from rollback_error
        raise
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if activated and os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)


def _make_export_readable(export_dir: str) -> None:
    """Give Nginx read access without accepting generated symlinks."""

    for current_dir, directory_names, file_names in os.walk(export_dir):
        if os.path.islink(current_dir):
            raise RuntimeError(f"Export contains an unsafe symlink: {current_dir}")
        os.chmod(current_dir, 0o755)
        for name in directory_names:
            path = os.path.join(current_dir, name)
            if os.path.islink(path):
                raise RuntimeError(f"Export contains an unsafe symlink: {path}")
            os.chmod(path, 0o755)
        for name in file_names:
            path = os.path.join(current_dir, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError(f"Export contains an unsafe file: {path}")
            os.chmod(path, 0o644)


def _published_url(username: str, game: str) -> str | None:
    try:
        with open(BASE_URL_FILE, encoding="utf-8") as url_file:
            base_url = url_file.read().strip().rstrip("/")
    except OSError:
        return None
    if not base_url:
        return None
    return f"{base_url}/games/{username}/{game}/"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not _GAME_NAME_PATTERN.fullmatch(args.game):
        print(
            "Error: game must use lowercase letters, digits, '-' or '_' and start "
            "with a letter or digit",
            file=sys.stderr,
        )
        return 2
    try:
        preset = _validate_preset(args.preset)
        account = _current_account()
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    project_dir = os.path.realpath(os.path.abspath(os.path.expanduser(args.project)))
    if not os.path.isfile(os.path.join(project_dir, "project.godot")):
        print(f"Error: no project.godot found in {project_dir}", file=sys.stderr)
        return 2

    user_root = os.path.join(GAMES_ROOT, account.pw_name)
    if os.path.islink(user_root) or not os.path.isdir(user_root):
        print(
            f"Error: managed publishing directory is unavailable: {user_root}",
            file=sys.stderr,
        )
        return 1
    if os.stat(user_root).st_uid != account.pw_uid:
        print(f"Error: publishing directory is not owned by {account.pw_name}", file=sys.stderr)
        return 1

    staging_dir = tempfile.mkdtemp(prefix=f".{args.game}-", dir=user_root)
    export_path = os.path.join(staging_dir, "index.html")
    command = [
        "godot",
        "--headless",
        "--path",
        project_dir,
        "--export-debug" if args.debug else "--export-release",
        preset,
        export_path,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not os.path.isfile(export_path):
        shutil.rmtree(staging_dir, ignore_errors=True)
        if result.returncode == 0:
            print("Error: Godot did not create index.html", file=sys.stderr)
            return 1
        return result.returncode

    destination_dir = os.path.join(user_root, args.game)
    try:
        _make_export_readable(staging_dir)
        _replace_export(staging_dir, destination_dir)
    except (OSError, RuntimeError) as exc:
        print(f"Error: could not activate export: {exc}", file=sys.stderr)
        return 1

    published_url = _published_url(account.pw_name, args.game)
    print(f"Published {args.game} to {published_url or destination_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
