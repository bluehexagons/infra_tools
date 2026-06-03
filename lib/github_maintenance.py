"""GitHub release and Actions storage maintenance helpers."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".build",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "venv",
}

_GITHUB_REPO_PATTERNS = (
    re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$"),
    re.compile(r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$"),
    re.compile(r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$"),
)


@dataclass(frozen=True)
class GitHubRepo:
    """A local git checkout that points at a GitHub repository."""

    root: str
    remote_url: str
    full_name: str


@dataclass(frozen=True)
class RepoSummary:
    """Storage summary for a GitHub repository."""

    repo: GitHubRepo
    releases: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    caches: list[dict[str, Any]]

    @property
    def release_size(self) -> int:
        return sum(_release_asset_size(release) for release in self.releases)

    @property
    def artifact_size(self) -> int:
        return sum((_int_field(artifact.get("size_in_bytes")) or 0) for artifact in self.artifacts)

    @property
    def cache_size(self) -> int:
        return sum((_int_field(cache.get("size_in_bytes")) or 0) for cache in self.caches)

    @property
    def expired_artifact_count(self) -> int:
        return sum(1 for artifact in self.artifacts if bool(artifact.get("expired")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo.full_name,
            "root": self.repo.root,
            "remote_url": self.repo.remote_url,
            "releases": {
                "count": len(self.releases),
                "bytes": self.release_size,
            },
            "artifacts": {
                "count": len(self.artifacts),
                "expired_count": self.expired_artifact_count,
                "bytes": self.artifact_size,
            },
            "caches": {
                "count": len(self.caches),
                "bytes": self.cache_size,
            },
        }


def add_maintenance_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the top-level maintenance command tree."""

    parser = subparsers.add_parser(
        "maintenance",
        help="Audit and prune GitHub releases, artifacts, and caches",
        description=(
            "Audit and prune GitHub repository storage across local checkouts. "
            "The maintenance command discovers git repositories from one or more "
            "roots, maps them to GitHub remotes, and then audits or prunes "
            "releases, Actions artifacts, and Actions caches."
        ),
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="maintenance_roots",
        default=[],
        help="Root directory to scan for git repositories; repeatable",
    )
    sub = parser.add_subparsers(dest="maintenance_command", help="Maintenance command")

    github = sub.add_parser("github", help="Audit and prune GitHub repository storage")
    github.add_argument(
        "--root",
        action="append",
        dest="github_roots",
        default=[],
        help="Root directory to scan for git repositories; repeatable",
    )
    github_sub = github.add_subparsers(dest="github_command", help="GitHub maintenance command")

    audit = github_sub.add_parser("audit", help="Show GitHub storage usage for discovered repos")
    audit.add_argument("--json", action="store_true", help="Output JSON instead of a table")
    audit.set_defaults(_handler=_cmd_github_audit)

    prune = github_sub.add_parser(
        "prune",
        help="Delete expired artifacts and old releases",
    )
    prune.add_argument(
        "--keep-releases",
        type=int,
        default=2,
        help="Keep this many newest releases per repo (default: 2)",
    )
    prune.add_argument(
        "--delete-expired-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete expired GitHub Actions artifacts (default: yes)",
    )
    prune.add_argument(
        "--delete-caches",
        action="store_true",
        help="Also delete stale Actions caches older than the threshold",
    )
    prune.add_argument(
        "--cache-older-than-days",
        type=int,
        default=90,
        help="Only delete caches last accessed at least this many days ago",
    )
    prune.add_argument("-y", "--yes", action="store_true", help="Run without prompting")
    prune.add_argument("--dry-run", action="store_true", help="Show planned deletions without deleting")
    prune.set_defaults(_handler=_cmd_github_prune)

    github.set_defaults(_handler=_cmd_github)
    parser.set_defaults(_handler=_cmd_maintenance)
    return parser


def run_maintenance_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed maintenance command."""

    handler = getattr(args, "_handler", None)
    if handler is None:
        print("Error: maintenance command required (github)")
        return 1
    try:
        return handler(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1


def _cmd_maintenance(args: argparse.Namespace) -> int:
    if getattr(args, "maintenance_command", None) is None:
        print("Error: maintenance command required (github)")
        return 1
    return 0


def _cmd_github(args: argparse.Namespace) -> int:
    if getattr(args, "github_command", None) is None:
        print("Error: github maintenance command required (audit, prune)")
        return 1
    return 0


def _cmd_github_audit(args: argparse.Namespace) -> int:
    repos = discover_github_repos(_selected_roots(args))
    summaries = [summarize_github_repo(repo) for repo in repos]
    if args.json:
        print(json.dumps([summary.to_dict() for summary in summaries], indent=2, sort_keys=True))
        return 0

    if not summaries:
        print("No GitHub repositories found.")
        return 0

    print(f"{'REPO':<34} {'REL':>4} {'REL MB':>8} {'ART':>4} {'ART MB':>8} {'CACHE':>5} {'CACHE MB':>9}")
    print("-" * 78)
    for summary in sorted(summaries, key=lambda item: item.repo.full_name):
        print(
            f"{summary.repo.full_name:<34} "
            f"{len(summary.releases):>4} {_format_mebibytes(summary.release_size):>8} "
            f"{len(summary.artifacts):>4} {_format_mebibytes(summary.artifact_size):>8} "
            f"{len(summary.caches):>5} {_format_mebibytes(summary.cache_size):>9}"
        )
    return 0


def _cmd_github_prune(args: argparse.Namespace) -> int:
    repos = discover_github_repos(_selected_roots(args))
    if not repos:
        print("No GitHub repositories found.")
        return 0

    plans: list[tuple[GitHubRepo, list[str], list[int], list[int]]] = []
    for repo in repos:
        summary = summarize_github_repo(repo)
        release_tags = _release_tags_to_delete(summary.releases, args.keep_releases)
        artifact_ids = _expired_artifact_ids(summary.artifacts) if args.delete_expired_artifacts else []
        cache_ids = (
            _stale_cache_ids(summary.caches, args.cache_older_than_days)
            if args.delete_caches
            else []
        )
        if release_tags or artifact_ids or cache_ids:
            plans.append((repo, release_tags, artifact_ids, cache_ids))

    if not plans:
        print("Nothing to prune.")
        return 0

    for repo, release_tags, artifact_ids, cache_ids in plans:
        print(f"== {repo.full_name} ==")
        if release_tags:
            print(f"  Releases to delete: {', '.join(release_tags)}")
        if artifact_ids:
            print(f"  Expired artifacts: {len(artifact_ids)}")
        if cache_ids:
            print(f"  Stale caches: {len(cache_ids)}")

    if args.dry_run:
        print("Dry run complete; no deletions performed.")
        return 0

    if not args.yes:
        response = input("Proceed with deletions? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 0

    for repo, release_tags, artifact_ids, cache_ids in plans:
        for tag in release_tags:
            _delete_release(repo.full_name, tag)
        for artifact_id in artifact_ids:
            _delete_artifact(repo.full_name, artifact_id)
        for cache_id in cache_ids:
            _delete_cache(repo.full_name, cache_id)

    print("Cleanup complete.")
    return 0


def _selected_roots(args: argparse.Namespace) -> list[str]:
    roots = list(getattr(args, "maintenance_roots", []))
    roots.extend(getattr(args, "github_roots", []))
    return roots or [os.getcwd()]


def discover_github_repos(roots: Iterable[str]) -> list[GitHubRepo]:
    """Discover local Git checkouts with GitHub remotes."""

    repos: dict[str, GitHubRepo] = {}
    for root in roots:
        for repo_root in _find_git_repo_roots(os.path.abspath(root)):
            remote_url = _git_remote_url(repo_root)
            if not remote_url:
                continue
            full_name = _parse_github_remote(remote_url)
            if not full_name:
                continue
            repos.setdefault(full_name, GitHubRepo(root=repo_root, remote_url=remote_url, full_name=full_name))
    return sorted(repos.values(), key=lambda repo: repo.full_name)


def summarize_github_repo(repo: GitHubRepo) -> RepoSummary:
    """Fetch releases, artifacts, and caches for a GitHub repo."""

    releases = _fetch_github_releases(repo.full_name)
    artifacts = _fetch_github_artifacts(repo.full_name)
    caches = _fetch_github_caches(repo.full_name)
    return RepoSummary(repo=repo, releases=releases, artifacts=artifacts, caches=caches)


def _find_git_repo_roots(root: str) -> Iterable[str]:
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        git_dir = os.path.join(dirpath, ".git")
        if os.path.isdir(git_dir) or os.path.isfile(git_dir):
            yield dirpath
            dirnames[:] = []


def _git_remote_url(repo_root: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_root, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _parse_github_remote(remote_url: str) -> str | None:
    for pattern in _GITHUB_REPO_PATTERNS:
        match = pattern.match(remote_url.strip())
        if match:
            return match.group("repo")
    return None


def _gh_api_paginated(endpoint: str) -> list[Any]:
    result = subprocess.run(
        ["gh", "api", "--paginate", endpoint],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"gh api failed for {endpoint}"
        raise RuntimeError(message)
    return _decode_json_stream(result.stdout)


def _decode_json_stream(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    length = len(text)
    while True:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            return values
        value, index = decoder.raw_decode(text, index)
        values.append(value)


def _fetch_github_releases(repo: str) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in _gh_api_paginated(f"/repos/{repo}/releases"):
        if isinstance(page, list):
            releases.extend(item for item in page if isinstance(item, dict))
    return releases


def _fetch_github_artifacts(repo: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for page in _gh_api_paginated(f"/repos/{repo}/actions/artifacts"):
        if not isinstance(page, dict):
            continue
        entries = page.get("artifacts", [])
        if isinstance(entries, list):
            artifacts.extend(item for item in entries if isinstance(item, dict))
    return artifacts


def _fetch_github_caches(repo: str) -> list[dict[str, Any]]:
    caches: list[dict[str, Any]] = []
    for page in _gh_api_paginated(f"/repos/{repo}/actions/caches"):
        if not isinstance(page, dict):
            continue
        entries = page.get("actions_caches", [])
        if isinstance(entries, list):
            caches.extend(item for item in entries if isinstance(item, dict))
    return caches


def _release_tags_to_delete(releases: list[dict[str, Any]], keep_releases: int) -> list[str]:
    if keep_releases < 0:
        raise ValueError("keep-releases must be zero or greater")
    ordered = sorted(
        [release for release in releases if isinstance(release.get("tag_name"), str)],
        key=lambda release: (_parse_timestamp(release.get("published_at")), str(release.get("tag_name"))),
        reverse=True,
    )
    return [str(release["tag_name"]) for release in ordered[keep_releases:]]


def _expired_artifact_ids(artifacts: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for artifact in artifacts:
        if artifact.get("expired") is True:
            artifact_id = _int_field(artifact.get("id"))
            if artifact_id is not None:
                ids.append(artifact_id)
    return ids


def _stale_cache_ids(caches: list[dict[str, Any]], older_than_days: int) -> list[int]:
    if older_than_days < 0:
        raise ValueError("cache-older-than-days must be zero or greater")
    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_days * 24 * 60 * 60)
    ids: list[int] = []
    for cache in caches:
        last_accessed = _timestamp_seconds(cache.get("last_accessed_at"))
        if last_accessed is None:
            continue
        if last_accessed < cutoff:
            cache_id = _int_field(cache.get("id"))
            if cache_id is not None:
                ids.append(cache_id)
    return ids


def _delete_release(repo: str, tag_name: str) -> None:
    _run_gh_delete(f"/repos/{repo}/releases/tags/{tag_name}")


def _delete_artifact(repo: str, artifact_id: int) -> None:
    _run_gh_delete(f"/repos/{repo}/actions/artifacts/{artifact_id}")


def _delete_cache(repo: str, cache_id: int) -> None:
    _run_gh_delete(f"/repos/{repo}/actions/caches/{cache_id}")


def _run_gh_delete(endpoint: str) -> None:
    result = subprocess.run(["gh", "api", "-X", "DELETE", endpoint], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"gh delete failed for {endpoint}"
        raise RuntimeError(message)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_seconds(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.timestamp()


def _int_field(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _release_asset_size(release: dict[str, Any]) -> int:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return 0
    total = 0
    for asset in assets:
        if isinstance(asset, dict):
            total += _int_field(asset.get("size")) or 0
    return total


def _format_mebibytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f}"
