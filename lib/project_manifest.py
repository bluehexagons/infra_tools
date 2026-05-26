"""Repo-side project manifest (``infra.json``) loader and validation.

A repository MAY ship an ``infra.json`` at its root describing how it should be
built and served. When present, the ``--deploy`` / ``DeploymentOrchestrator``
path uses it as the source of truth, overriding ``detect_project_type()``. When
absent, behavior is unchanged (fully backward compatible).

This module is phase 1 of ``docs/plans/PROJECT_MANIFEST.md``: parsing,
dataclasses, and strict validation only. Orchestrator wiring lands in phase 2.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from lib.types import StrDict, StrList
from lib.validators import validate_host

MANIFEST_FILENAME = "infra.json"
SUPPORTED_VERSION = 1
MIN_PORT = 1024
MAX_PORT = 65535

_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")

_COMMON_FIELDS = {"name", "type", "domain", "path", "build", "env"}
_STATIC_FIELDS = {"output"}
_SERVICE_FIELDS = {
    "binary",
    "exec",
    "port",
    "systemd_unit",
    "env_file",
    "reverse_proxy",
    "health",
    "working_dir",
}


@dataclass
class Component:
    """A single deployable component declared in a manifest."""

    name: str
    type: str
    domain: str
    path: str = "/"
    build: StrList = field(default_factory=list)
    env: StrDict = field(default_factory=dict)
    # static
    output: Optional[str] = None
    # service
    binary: Optional[str] = None
    exec: Optional[str] = None
    port: Optional[int] = None
    systemd_unit: Optional[str] = None
    env_file: Optional[str] = None
    reverse_proxy: bool = True
    health: Optional[str] = None
    working_dir: Optional[str] = None

    @property
    def is_static(self) -> bool:
        return self.type == "static"

    @property
    def is_service(self) -> bool:
        return self.type == "service"


@dataclass
class Manifest:
    """A parsed, validated ``infra.json``."""

    version: int
    components: list[Component]


def load_manifest(repo_path: str) -> Optional[Manifest]:
    """Load and validate the manifest at ``repo_path``, or None if absent.

    Raises ValueError on malformed JSON or any validation failure so callers
    fail fast instead of deploying a half-understood repo.
    """
    manifest_path = os.path.join(repo_path, MANIFEST_FILENAME)
    if not os.path.exists(manifest_path):
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{MANIFEST_FILENAME}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{MANIFEST_FILENAME}: cannot read: {exc}") from exc

    return parse_manifest(data)


def parse_manifest(data: object) -> Manifest:
    """Validate an already-decoded manifest object into a Manifest."""
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_FILENAME} must be a JSON object")

    _reject_unknown_keys(data, {"version", "components"}, MANIFEST_FILENAME)

    version = data.get("version")
    if version != SUPPORTED_VERSION:
        raise ValueError(
            f"unsupported manifest version: {version!r} (expected {SUPPORTED_VERSION})"
        )

    components_raw = data.get("components")
    if not isinstance(components_raw, list) or not components_raw:
        raise ValueError("'components' must be a non-empty array")

    components: list[Component] = []
    seen: set[str] = set()
    for index, entry in enumerate(components_raw):
        component = _parse_component(entry, index)
        if component.name in seen:
            raise ValueError(f"duplicate component name: {component.name!r}")
        seen.add(component.name)
        components.append(component)

    return Manifest(version=version, components=components)


def _parse_component(entry: object, index: int) -> Component:
    where = f"components[{index}]"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be an object")

    comp_type = entry.get("type")
    if comp_type == "static":
        allowed = _COMMON_FIELDS | _STATIC_FIELDS
    elif comp_type == "service":
        allowed = _COMMON_FIELDS | _SERVICE_FIELDS
    else:
        raise ValueError(f"{where}: type must be 'static' or 'service', got {comp_type!r}")

    _reject_unknown_keys(entry, allowed, where)

    name = _require_str(entry, "name", where)
    if not _NAME_PATTERN.match(name):
        raise ValueError(f"{where}: name {name!r} must match {_NAME_PATTERN.pattern}")
    where = f"component {name!r}"

    domain = _require_str(entry, "domain", where)
    if not validate_host(domain):
        raise ValueError(f"{where}: invalid domain: {domain}")

    path = entry.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"{where}: path must be a string starting with '/'")

    build = _parse_build(entry.get("build"), where)
    env = _parse_env(entry.get("env"), where)

    common = dict(
        name=name,
        type=comp_type,
        domain=domain,
        path=path,
        build=build,
        env=env,
    )

    if comp_type == "static":
        output = _require_str(entry, "output", where)
        _require_repo_relative(output, "output", where)
        return Component(output=output, **common)

    return _parse_service(entry, where, common)


def _parse_service(entry: dict, where: str, common: dict) -> Component:
    binary = entry.get("binary")
    exec_cmd = entry.get("exec")
    if (binary is None) == (exec_cmd is None):
        raise ValueError(f"{where}: exactly one of 'binary' or 'exec' is required")
    if binary is not None:
        if not isinstance(binary, str) or not binary:
            raise ValueError(f"{where}: binary must be a non-empty string")
        _require_repo_relative(binary, "binary", where)
    if exec_cmd is not None and (not isinstance(exec_cmd, str) or not exec_cmd):
        raise ValueError(f"{where}: exec must be a non-empty string")

    port = entry.get("port")
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError(f"{where}: port must be an integer")
    if not MIN_PORT <= port <= MAX_PORT:
        raise ValueError(f"{where}: port must be between {MIN_PORT} and {MAX_PORT}, got {port}")

    systemd_unit = entry.get("systemd_unit")
    if systemd_unit is not None:
        if not isinstance(systemd_unit, str) or not systemd_unit:
            raise ValueError(f"{where}: systemd_unit must be a non-empty string")
        _require_repo_relative(systemd_unit, "systemd_unit", where)

    env_file = entry.get("env_file")
    if env_file is not None:
        if not isinstance(env_file, str) or not os.path.isabs(env_file):
            raise ValueError(f"{where}: env_file must be an absolute server-side path")

    reverse_proxy = entry.get("reverse_proxy", True)
    if not isinstance(reverse_proxy, bool):
        raise ValueError(f"{where}: reverse_proxy must be a boolean")

    health = entry.get("health")
    if health is not None and (not isinstance(health, str) or not health.startswith("/")):
        raise ValueError(f"{where}: health must be a string starting with '/'")

    working_dir = entry.get("working_dir")
    if working_dir is not None and (not isinstance(working_dir, str) or not working_dir):
        raise ValueError(f"{where}: working_dir must be a non-empty string")

    return Component(
        binary=binary,
        exec=exec_cmd,
        port=port,
        systemd_unit=systemd_unit,
        env_file=env_file,
        reverse_proxy=reverse_proxy,
        health=health,
        working_dir=working_dir,
        **common,
    )


def _parse_build(value: object, where: str) -> StrList:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{where}: build command must be non-empty")
        return [value]
    if isinstance(value, list):
        commands: StrList = []
        for command in value:
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"{where}: each build command must be a non-empty string")
            commands.append(command)
        if not commands:
            raise ValueError(f"{where}: build array must not be empty")
        return commands
    raise ValueError(f"{where}: build must be a string or array of strings")


def _parse_env(value: object, where: str) -> StrDict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{where}: env must be an object of string values")
    env: StrDict = {}
    for key, val in value.items():
        if not isinstance(val, str):
            raise ValueError(f"{where}: env value for {key!r} must be a string")
        env[key] = val
    return env


def _require_str(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}: {key} is required and must be a non-empty string")
    return value


def _require_repo_relative(value: str, key: str, where: str) -> None:
    """Reject absolute paths and any that escape the repo root via '..'."""
    if os.path.isabs(value):
        raise ValueError(f"{where}: {key} must be relative to the repo root: {value}")
    normalized = os.path.normpath(value)
    if normalized == ".." or normalized.startswith(".." + os.sep):
        raise ValueError(f"{where}: {key} must not escape the repo root: {value}")


def _reject_unknown_keys(data: dict, allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
