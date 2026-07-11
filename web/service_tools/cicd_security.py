"""Validation helpers for the CI/CD webhook trust boundary."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit


MAX_WEBHOOK_PAYLOAD_BYTES = 1024 * 1024
MAX_JOB_FILE_BYTES = 64 * 1024

_COMMIT_SHA_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_WORKSPACE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def validate_commit_sha(value: object) -> str:
    """Return a normalized Git object ID accepted from a push webhook."""

    if not isinstance(value, str) or not _COMMIT_SHA_PATTERN.fullmatch(value):
        raise ValueError("commit SHA must be a 40- or 64-character hexadecimal object ID")

    normalized = value.lower()
    if not normalized.strip("0"):
        raise ValueError("deleted refs do not identify a buildable commit")
    return normalized


def validate_branch_ref(value: object) -> tuple[str, str]:
    """Validate a fully qualified Git branch ref and return it with its branch."""

    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise ValueError("ref must identify a branch under refs/heads/")

    branch = value.removeprefix("refs/heads/")
    if not branch or len(branch) > 255:
        raise ValueError("branch name must contain between 1 and 255 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in branch):
        raise ValueError("branch name must not contain control characters")
    if any(char in branch for char in " ~^:?*[\\"):
        raise ValueError("branch name contains a character prohibited by Git")
    if ".." in branch or "@{" in branch or "//" in branch:
        raise ValueError("branch name contains a prohibited sequence")
    if branch.startswith(("/", ".")) or branch.endswith(("/", ".", ".lock")):
        raise ValueError("branch name has a prohibited prefix or suffix")
    if any(component in {"", ".", ".."} or component.endswith(".lock") for component in branch.split("/")):
        raise ValueError("branch name contains a prohibited path component")

    return value, branch


def validate_repo_url(value: object) -> str:
    """Validate the bounded repository URL copied into a job file."""

    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("repository URL must contain between 1 and 2048 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("repository URL must not contain control characters")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.username is not None:
        raise ValueError("HTTP repository URLs must not embed credentials")
    return value


def validate_pusher(value: object) -> str:
    """Validate the display-only pusher name before logging it."""

    if not isinstance(value, str) or not value or len(value) > 255:
        raise ValueError("pusher name must contain between 1 and 255 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("pusher name must not contain control characters")
    return value


def validate_job_data(job_data: object) -> tuple[str, str, str, str, str]:
    """Validate an executor job and return normalized security-sensitive fields."""

    if not isinstance(job_data, dict):
        raise ValueError("job data must be a JSON object")

    repo_url = validate_repo_url(job_data.get("repo_url"))
    ref, branch = validate_branch_ref(job_data.get("ref"))
    commit_sha = validate_commit_sha(job_data.get("commit_sha"))
    pusher = validate_pusher(job_data.get("pusher", "unknown"))
    return repo_url, ref, branch, commit_sha, pusher


def get_workspace_name(repo_url: str) -> str:
    """Return a readable, collision-resistant directory name for a repository."""

    validated_url = validate_repo_url(repo_url)
    parsed = urlsplit(validated_url)
    path = parsed.path if parsed.scheme else validated_url.rsplit(":", 1)[-1]
    repo_name = path.rstrip("/").rsplit("/", 1)[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    safe_name = _WORKSPACE_COMPONENT_PATTERN.sub("-", repo_name).strip(".-_") or "repository"
    safe_name = safe_name[:80]
    url_digest = hashlib.sha256(validated_url.encode("utf-8")).hexdigest()[:12]
    return f"{safe_name}-{url_digest}"
