#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
import tempfile

from lib.config import SetupConfig
from lib.workspace import ensure_workspace_dir, get_credentials_path


CREDENTIALS_VERSION = 1


def _normalize_credential_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise ValueError("Credential username must not be empty")
    return normalized


def _normalize_credential_password(password: str) -> str:
    normalized = password.strip()
    if not normalized:
        raise ValueError("Credential password must not be empty")
    return normalized


def _ensure_secure_credentials_file(path: str) -> None:
    if not os.path.exists(path):
        return

    current_mode = os.stat(path).st_mode & 0o777
    if current_mode == 0o600:
        return

    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise ValueError(f"Credential store must use 0600 permissions: {path}") from exc

    updated_mode = os.stat(path).st_mode & 0o777
    if updated_mode != 0o600:
        raise ValueError(f"Credential store must use 0600 permissions: {path}")


def load_workspace_credentials(workspace: str | None = None) -> dict[str, str]:
    """Load saved workspace credentials."""
    ensure_workspace_dir(workspace)
    credentials_path = get_credentials_path(workspace)
    if not os.path.exists(credentials_path):
        return {}

    _ensure_secure_credentials_file(credentials_path)

    with open(credentials_path, "r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if not isinstance(payload, dict):
        raise ValueError("Credential store must contain a JSON object")

    if payload.get("version") != CREDENTIALS_VERSION:
        raise ValueError("Unsupported credential store version")

    credentials_obj = payload.get("credentials", {})
    if not isinstance(credentials_obj, dict):
        raise ValueError("Credential store credentials field must be an object")

    credentials: dict[str, str] = {}
    for username, entry in credentials_obj.items():
        normalized_username = _normalize_credential_username(str(username))
        if not isinstance(entry, dict):
            raise ValueError(f"Credential entry for {normalized_username} must be an object")
        password = entry.get("password")
        if not isinstance(password, str):
            raise ValueError(f"Credential entry for {normalized_username} must contain a password string")
        credentials[normalized_username] = password

    return credentials


def save_workspace_credentials(credentials: dict[str, str], workspace: str | None = None) -> None:
    """Persist workspace credentials using the REVIEW_1 JSON layout."""
    workspace_dir = ensure_workspace_dir(workspace)
    credentials_path = get_credentials_path(workspace)
    normalized_credentials = {
        _normalize_credential_username(username): _normalize_credential_password(password)
        for username, password in credentials.items()
    }
    payload = {
        "version": CREDENTIALS_VERSION,
        "credentials": {
            username: {"password": password}
            for username, password in sorted(normalized_credentials.items())
        },
    }

    fd, temp_path = tempfile.mkstemp(
        dir=workspace_dir,
        prefix=".credentials-",
        suffix=".json",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, indent=2, sort_keys=True)
            file_obj.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, credentials_path)
        os.chmod(credentials_path, 0o600)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def set_workspace_credential(username: str, password: str, workspace: str | None = None) -> None:
    """Add or replace a workspace credential."""
    credentials = load_workspace_credentials(workspace)
    credentials[_normalize_credential_username(username)] = _normalize_credential_password(password)
    save_workspace_credentials(credentials, workspace)


def remove_workspace_credential(username: str, workspace: str | None = None) -> bool:
    """Remove a saved workspace credential."""
    normalized_username = _normalize_credential_username(username)
    credentials = load_workspace_credentials(workspace)
    removed = credentials.pop(normalized_username, None) is not None
    if removed or os.path.exists(get_credentials_path(workspace)):
        save_workspace_credentials(credentials, workspace)
    return removed


def list_workspace_credentials(workspace: str | None = None) -> list[str]:
    """Return saved credential usernames."""
    return sorted(load_workspace_credentials(workspace))


def store_cli_credentials(config: SetupConfig, workspace: str | None = None) -> None:
    """Persist credentials supplied on the command line."""
    credentials = load_workspace_credentials(workspace)
    if config.share_credentials:
        for username, password in config.share_credentials:
            credentials[_normalize_credential_username(username)] = _normalize_credential_password(password)

    if config.samba_shares:
        for share_spec in config.samba_shares:
            if len(share_spec) < 4:
                continue
            for user_spec in share_spec[3].split(","):
                normalized_user = user_spec.strip()
                if ":" not in normalized_user:
                    continue
                username, password = normalized_user.split(":", 1)
                credentials[_normalize_credential_username(username)] = _normalize_credential_password(password)

    if config.smb_mounts:
        for mount_spec in config.smb_mounts:
            if len(mount_spec) < 3 or ":" not in mount_spec[2]:
                continue
            username, password = mount_spec[2].split(":", 1)
            credentials[_normalize_credential_username(username)] = _normalize_credential_password(password)

    if not credentials:
        return

    save_workspace_credentials(credentials, workspace)


def _collect_required_share_usernames(config: SetupConfig) -> list[str]:
    usernames: list[str] = []
    seen_usernames: set[str] = set()

    if not config.samba_shares:
        return usernames

    for share_spec in config.samba_shares:
        if len(share_spec) < 4:
            continue
        for user_spec in share_spec[3].split(","):
            normalized_user = user_spec.strip()
            if not normalized_user or ":" in normalized_user or normalized_user in seen_usernames:
                continue
            seen_usernames.add(normalized_user)
            usernames.append(normalized_user)

    return usernames


def _resolve_share_credentials(config: SetupConfig, credential_map: dict[str, str]) -> list[list[str]]:
    resolved_credentials: list[list[str]] = []
    seen_usernames: set[str] = set()

    if config.share_credentials:
        for username, password in config.share_credentials:
            normalized_username = _normalize_credential_username(username)
            normalized_password = _normalize_credential_password(password)
            credential_map[normalized_username] = normalized_password
            if normalized_username not in seen_usernames:
                seen_usernames.add(normalized_username)
                resolved_credentials.append([normalized_username, normalized_password])

    for username in _collect_required_share_usernames(config):
        password = credential_map.get(username)
        if password is None:
            raise ValueError(
                f"Missing credential for share user: {username}. "
                "Use --credential USERNAME PASSWORD or infra_tools.py credentials set USERNAME PASSWORD"
            )
        if username not in seen_usernames:
            seen_usernames.add(username)
            resolved_credentials.append([username, password])

    return resolved_credentials


def _resolve_named_smb_mounts(
    smb_mounts: list[list[str]] | None,
    credential_map: dict[str, str],
) -> list[list[str]] | None:
    if not smb_mounts:
        return smb_mounts

    resolved_mounts: list[list[str]] = []
    for mount_spec in smb_mounts:
        resolved_spec = list(mount_spec)
        if len(resolved_spec) >= 3 and ":" not in resolved_spec[2]:
            username = _normalize_credential_username(resolved_spec[2])
            password = credential_map.get(username)
            if password is None:
                raise ValueError(
                    f"Missing credential for SMB mount user: {username}. "
                    "Use --credential USERNAME PASSWORD or infra_tools.py credentials set USERNAME PASSWORD"
                )
            resolved_spec[2] = f"{username}:{password}"
        resolved_mounts.append(resolved_spec)
    return resolved_mounts


def prepare_runtime_config(config: SetupConfig, workspace: str | None = None) -> SetupConfig:
    """Return a runtime config with workspace credentials resolved."""
    runtime_config = copy.deepcopy(config)
    credential_map = load_workspace_credentials(workspace)
    runtime_config.share_credentials = _resolve_share_credentials(runtime_config, credential_map) or None
    runtime_config.smb_mounts = _resolve_named_smb_mounts(runtime_config.smb_mounts, credential_map)
    return runtime_config
