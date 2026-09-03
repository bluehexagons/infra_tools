"""Bounded, validated event storage for the infra-tools web panel."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from lib.atomic_io import write_text_atomic
from lib.types import JSON, JSONDict
from lib.validation import validate_filesystem_path


WEB_PANEL_DATA_DIR = "/var/lib/infra_tools/web-panel"
WEB_PANEL_AUDIT_DIR = f"{WEB_PANEL_DATA_DIR}/audit"
WEB_PANEL_AUDIT_SNAPSHOT = f"{WEB_PANEL_AUDIT_DIR}/events.json"
WEB_PANEL_NOTIFICATION_DIR = f"{WEB_PANEL_DATA_DIR}/notifications"
WEB_PANEL_NOTIFICATION_LOG = f"{WEB_PANEL_NOTIFICATION_DIR}/events.jsonl"
WEB_PANEL_INGEST_TOKEN = "/etc/infra-tools/web-panel/notification-ingest.token"
WEB_PANEL_NOTIFICATION_ENDPOINT = "/api/v1/notifications"

_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_NOTIFICATION_BYTES = 32 * 1024
_MAX_NOTIFICATION_EVENTS = 100
_MAX_AUDIT_EVENTS = 100
_MAX_AUDIT_ISSUES = 10
_MAX_DATA_DEPTH = 6
_MAX_DATA_ITEMS = 100


def _bounded_string(
    value: object,
    name: str,
    *,
    maximum: int,
    required: bool = True,
) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its size limit")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _validated_json(value: object, *, depth: int = 0) -> JSON:
    if depth > _MAX_DATA_DEPTH:
        raise ValueError("notification data is nested too deeply")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            return _bounded_string(
                value,
                "notification data value",
                maximum=2048,
                required=False,
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("notification data contains a non-finite number")
        return value
    if isinstance(value, list):
        if len(value) > _MAX_DATA_ITEMS:
            raise ValueError("notification data list has too many items")
        return [_validated_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAX_DATA_ITEMS:
            raise ValueError("notification data object has too many fields")
        result: JSONDict = {}
        for key, item in value.items():
            safe_key = _bounded_string(
                key,
                "notification data field",
                maximum=128,
            )
            result[safe_key] = _validated_json(item, depth=depth + 1)
        return result
    raise ValueError("notification data contains an unsupported value")


def validate_notification_payload(value: object) -> JSONDict:
    """Return a canonical schema-v2 notification suitable for local storage."""

    schema_version = (
        value.get("schema_version") if isinstance(value, dict) else None
    )
    if (
        not isinstance(value, dict)
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 2
    ):
        raise ValueError("notification must use schema_version 2")
    event = value.get("event")
    operator = value.get("operator")
    data = value.get("data", {})
    if not isinstance(event, dict) or not isinstance(operator, dict):
        raise ValueError("notification event and operator must be objects")
    if not isinstance(data, dict):
        raise ValueError("notification data must be an object")

    event_type = _bounded_string(event.get("type"), "event.type", maximum=128)
    state = _bounded_string(event.get("state"), "event.state", maximum=16)
    status = _bounded_string(event.get("status"), "event.status", maximum=16)
    if state not in {"firing", "resolved", "success"}:
        raise ValueError("event.state is invalid")
    if status not in {"good", "info", "warning", "error"}:
        raise ValueError("event.status is invalid")
    deduplication_key = event.get("deduplication_key")
    if deduplication_key is not None:
        deduplication_key = _bounded_string(
            deduplication_key,
            "event.deduplication_key",
            maximum=256,
        )

    actions = operator.get("suggested_actions", [])
    if not isinstance(actions, list) or len(actions) > 10:
        raise ValueError("operator.suggested_actions is invalid")
    safe_actions = [
        _bounded_string(action, "suggested action", maximum=500)
        for action in actions
    ]
    canonical: JSONDict = {
        "schema_version": 2,
        "event": {
            "type": event_type,
            "state": state,
            "status": status,
            "deduplication_key": deduplication_key,
        },
        "operator": {
            "subject": _bounded_string(
                operator.get("subject"), "operator.subject", maximum=200
            ),
            "job": _bounded_string(
                operator.get("job"), "operator.job", maximum=100
            ),
            "system": _bounded_string(
                operator.get("system"), "operator.system", maximum=255
            ),
            "what_happened": _bounded_string(
                operator.get("what_happened"),
                "operator.what_happened",
                maximum=4000,
            ),
            "suggested_actions": safe_actions,
            "details": _bounded_string(
                operator.get("details", ""),
                "operator.details",
                maximum=8000,
                required=False,
            ),
        },
        "data": _validated_json(data),
    }
    if len(json.dumps(canonical, separators=(",", ":")).encode("utf-8")) > (
        _MAX_NOTIFICATION_BYTES
    ):
        raise ValueError("notification exceeds its storage size limit")
    return canonical


def _read_regular_text(path: str, *, maximum: int = _MAX_FILE_BYTES) -> str | None:
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        if not 0 < os.path.getsize(path) <= maximum:
            return None
        with open(path, "rb") as file_obj:
            content = file_obj.read(maximum + 1)
        if len(content) > maximum:
            return None
        return content.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return None


def load_ingest_token(path: str = WEB_PANEL_INGEST_TOKEN) -> str:
    """Load a fixed-format bearer token without accepting unsafe file types."""

    content = _read_regular_text(path, maximum=512)
    token = content.strip() if content is not None else ""
    if not 32 <= len(token) <= 256 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in token
    ):
        raise RuntimeError("Notification ingest token is missing or invalid")
    return token


def load_audit_snapshot(
    path: str = WEB_PANEL_AUDIT_SNAPSHOT,
) -> dict[str, Any]:
    """Load the root-exported audit snapshot, failing closed on malformed data."""

    unavailable = {
        "status": "unavailable",
        "issues": ["No valid audit snapshot is available."],
        "events": [],
    }
    content = _read_regular_text(path)
    if content is None:
        return unavailable
    try:
        payload = json.loads(content)
    except (RecursionError, ValueError):
        return unavailable
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return unavailable
    status = payload.get("status")
    generated_at = payload.get("generated_at")
    events = payload.get("events")
    if status not in {"ok", "degraded", "unavailable"} or not isinstance(
        events, list
    ):
        return unavailable

    issues = payload.get("issues", [])
    safe_issues: list[str] = []
    if isinstance(issues, list):
        safe_issues = [
            issue[:300]
            for issue in issues[:_MAX_AUDIT_ISSUES]
            if isinstance(issue, str)
            and issue
            and not any(ord(character) < 32 for character in issue)
        ]
    if status != "ok" and not safe_issues:
        safe_issues = ["Audit collection did not complete successfully."]
    safe_events: list[JSONDict] = []
    for event in events[:_MAX_AUDIT_EVENTS]:
        if not isinstance(event, dict):
            continue
        key = event.get("key")
        meaning = event.get("meaning")
        timestamp = event.get("timestamp")
        if not all(isinstance(item, str) and item for item in (key, meaning, timestamp)):
            continue
        record: JSONDict = {
            "key": key[:64],
            "meaning": meaning[:200],
            "timestamp": timestamp[:64],
            "severity": "warning" if event.get("severity") == "warning" else "info",
        }
        for name in ("paths", "operations", "actors", "executables"):
            values = event.get(name)
            if isinstance(values, list):
                record[name] = [
                    item[:512]
                    for item in values[:10]
                    if isinstance(item, str) and item
                ]
        safe_events.append(record)
    return {
        "status": status,
        "generated_at": generated_at[:64] if isinstance(generated_at, str) else "",
        "issues": safe_issues,
        "events": safe_events,
    }


def load_notification_events(
    path: str = WEB_PANEL_NOTIFICATION_LOG,
) -> list[JSONDict]:
    """Return the newest validated notification records from the bounded log."""

    content = _read_regular_text(path)
    if content is None:
        return []
    events: list[JSONDict] = []
    for line in content.splitlines()[-_MAX_NOTIFICATION_EVENTS:]:
        try:
            record = json.loads(line)
        except (RecursionError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        received_at = record.get("received_at")
        source_ip = record.get("source_ip")
        try:
            notification = validate_notification_payload(record.get("notification"))
        except ValueError:
            continue
        if not isinstance(received_at, str) or not isinstance(source_ip, str):
            continue
        events.append(
            {
                "received_at": received_at[:64],
                "source_ip": source_ip[:64],
                "notification": notification,
            }
        )
    return events


def append_notification_event(
    notification: JSONDict,
    source_ip: str,
    *,
    path: str = WEB_PANEL_NOTIFICATION_LOG,
) -> None:
    """Append one notification while retaining only the latest bounded history."""

    notification = validate_notification_payload(notification)
    source_ip = _bounded_string(
        source_ip,
        "notification source address",
        maximum=64,
    )
    validate_filesystem_path(path, must_exist=False)
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
        raise RuntimeError(f"Refusing unsafe notification log: {path}")
    parent = os.path.dirname(path)
    if os.path.islink(parent) or not os.path.isdir(parent):
        raise RuntimeError(f"Notification log directory is unavailable: {parent}")
    record: JSONDict = {
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_ip": source_ip[:64],
        "notification": notification,
    }
    events = load_notification_events(path)
    events.append(record)
    events = events[-_MAX_NOTIFICATION_EVENTS:]
    content = "".join(
        json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
        for event in events
    )
    write_text_atomic(path, content, mode=0o600)
