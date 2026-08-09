#!/usr/bin/env python3
"""
Security Event Monitor

Checks security logs for notable events and sends notifications via the
configured infra_tools notification targets. Runs every 15 minutes.

Event sources (where installed):
  - fail2ban: ban/unban events from /var/log/fail2ban.log
  - auditd: identity, sudoers, SSH config, module, and privileged-exec events
  - SSH: failed authentication attempts from the system journal
  - XRDP: TLS certificate/key validity, expiry, permissions, and readability

Severity rules:
  error   — auditd detected writes to identity/sudoers/SSH-config files or
             kernel module loads, or XRDP TLS material is unusable
  warning — fail2ban banned an IP address, or the XRDP certificate expires soon
  info    — SSH auth failures at or above the reporting threshold (default: 5)

Logs to: /var/log/infra_tools/security/security_monitor.log
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from logging import ERROR, WARNING

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger, log_event
from lib.atomic_io import write_json_atomic
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.validation import validate_filesystem_path
from lib.xrdp_certificate import XrdpCertificateHealth, inspect_xrdp_certificate

logger = get_service_logger('security_monitor', 'security', use_syslog=True)

_STATE_FILE = '/opt/infra_tools/state/security_monitor_state.json'
_FAIL2BAN_LOG = '/var/log/fail2ban.log'
_SSH_FAILURE_THRESHOLD = 5

# fail2ban log line pattern — local-time timestamp + jail + action + IP.
# Jail names may contain hyphens (e.g. nginx-http-auth), so [^\]]+ is used.
_BAN_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+'
    r' fail2ban\.actions\s+\[.*?\]:\s+(?:WARNING|NOTICE)\s+\[([^\]]+)\] (Ban|Unban) (\S+)'
)

# auditd keys that trigger error-level notifications (system integrity events)
_CRITICAL_KEYS = ('identity', 'sudoers', 'sshd_config', 'modules')
# auditd keys included in notifications but not used to raise severity —
# 'privileged' fires on every sudo call, which is routine admin activity.
_INFO_KEYS = ('privileged',)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, object]:
    try:
        with open(_STATE_FILE) as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(state: dict[str, object]) -> None:
    """Persist the collection cursor without exposing a partial JSON file."""
    validate_filesystem_path(_STATE_FILE, must_exist=False)
    write_json_atomic(_STATE_FILE, state, mode=0o600, sort_keys=True)


# ---------------------------------------------------------------------------
# fail2ban
# ---------------------------------------------------------------------------

def _check_fail2ban(since: datetime) -> tuple[list[str], list[str], str | None]:
    """Return ban lines, unban lines, and any collection error."""
    bans: list[str] = []
    unbans: list[str] = []
    if not os.path.exists(_FAIL2BAN_LOG):
        return bans, unbans, None
    try:
        with open(_FAIL2BAN_LOG) as f:
            for line in f:
                m = _BAN_RE.match(line)
                if not m:
                    continue
                try:
                    ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if ts < since:
                    continue
                jail, action, ip = m.group(2), m.group(3), m.group(4)
                entry = f"  {m.group(1)}  [{jail}] {action.lower()}ned {ip}"
                if action == 'Ban':
                    bans.append(entry)
                else:
                    unbans.append(entry)
    except OSError as exc:
        return bans, unbans, f'fail2ban log: {exc}'
    return bans, unbans, None


# ---------------------------------------------------------------------------
# auditd
# ---------------------------------------------------------------------------

def _ausearch_has_events(key: str, since: datetime) -> tuple[bool, str | None]:
    """Return whether auditd has matching events and any collection error."""
    since_date = since.strftime('%m/%d/%Y')
    since_time = since.strftime('%H:%M:%S')
    try:
        result = subprocess.run(
            ['ausearch', '--start', since_date, since_time, '-k', key],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip()), None
        if result.returncode == 1:
            return False, None
        details = result.stderr.strip() or f'ausearch exited {result.returncode}'
        return False, f'audit key {key}: {details}'
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f'audit key {key}: {exc}'


def _check_auditd(since: datetime) -> tuple[list[str], bool, list[str]]:
    """Return triggered keys, critical status, and collection errors."""
    if not shutil.which('ausearch'):
        return [], False, []
    triggered: list[str] = []
    has_critical = False
    errors: list[str] = []
    for key in _CRITICAL_KEYS + _INFO_KEYS:
        has_events, error = _ausearch_has_events(key, since)
        if error:
            errors.append(error)
        if has_events:
            triggered.append(key)
            if key in _CRITICAL_KEYS:
                has_critical = True
    return triggered, has_critical, errors


# ---------------------------------------------------------------------------
# SSH failures
# ---------------------------------------------------------------------------

def _check_ssh_failures(since: datetime) -> tuple[int, str | None]:
    """Count SSH authentication failures and return any collection error."""
    since_str = since.strftime('%Y-%m-%d %H:%M:%S')
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'sshd', '-u', 'ssh',
             '--since', since_str, '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or f'journalctl exited {result.returncode}'
            return 0, f'SSH journal: {details}'
        count = 0
        for line in result.stdout.splitlines():
            if 'Failed password' in line or 'Invalid user' in line:
                count += 1
        return count, None
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 0, f'SSH journal: {exc}'


# ---------------------------------------------------------------------------
# XRDP certificate health
# ---------------------------------------------------------------------------

def _certificate_health_event(
    state: dict[str, object],
    health: XrdpCertificateHealth,
) -> tuple[str, str, str] | None:
    """Return a notification event only when certificate health changes."""
    previous_issue = state.get("rdp_certificate_issue")
    if not isinstance(previous_issue, str):
        previous_issue = ""
    previous_fingerprint = state.get("rdp_certificate_fingerprint")
    if not isinstance(previous_fingerprint, str):
        previous_fingerprint = ""

    current_issue = health.issue or ""
    if current_issue:
        fingerprint_unchanged = (
            not previous_fingerprint
            or not health.fingerprint
            or previous_fingerprint == health.fingerprint
        )
        if current_issue == previous_issue and fingerprint_unchanged:
            return None
        return (
            health.status,
            f"XRDP TLS certificate {health.status}",
            current_issue,
        )

    if health.status == "ok" and previous_issue:
        return (
            "info",
            "XRDP TLS certificate recovered",
            f"Certificate health is now valid: {health.certificate_path}",
        )

    if (
        health.status == "ok"
        and previous_fingerprint
        and health.fingerprint
        and previous_fingerprint != health.fingerprint
    ):
        return (
            "info",
            "XRDP TLS certificate changed",
            f"Certificate fingerprint changed: {health.certificate_path}",
        )
    return None


def _next_state(now: datetime, health: XrdpCertificateHealth) -> dict[str, object]:
    """Build persisted collection and certificate state."""
    next_state: dict[str, object] = {"last_run": now.isoformat()}
    if health.status != "not_configured":
        next_state["rdp_certificate_status"] = health.status
        next_state["rdp_certificate_issue"] = health.issue or ""
        next_state["rdp_certificate_fingerprint"] = health.fingerprint or ""
    return next_state


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    log_event(logger, "Starting security monitor check")

    notification_configs = load_notification_configs_from_state(logger)
    if not notification_configs:
        log_event(
            logger,
            "No notification targets configured; security events will be logged locally",
        )

    state = _load_state()
    now = datetime.now()

    if 'last_run' in state:
        try:
            last_run = state['last_run']
            if not isinstance(last_run, str):
                raise TypeError('last_run must be a string')
            since = datetime.fromisoformat(last_run)
            if since.tzinfo is not None:
                since = since.astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            since = now - timedelta(minutes=15)
    else:
        since = now - timedelta(minutes=15)
    if since > now:
        since = now - timedelta(minutes=15)

    bans, unbans, fail2ban_error = _check_fail2ban(since)
    audit_keys, audit_critical, audit_errors = _check_auditd(since)
    ssh_failures, ssh_error = _check_ssh_failures(since)
    certificate_health = inspect_xrdp_certificate()
    collection_errors = [
        error
        for error in (fail2ban_error, *audit_errors, ssh_error)
        if error
    ]
    if collection_errors:
        details = '\n'.join(collection_errors)
        log_event(
            logger,
            'Security event collection failed; retaining previous cursor',
            level=WARNING,
            errors=details,
        )
        send_notification_safe(
            notification_configs,
            subject='Error: security monitor collection failed',
            job='security_monitor',
            status='error',
            message='One or more security event sources could not be read.',
            details=details,
            logger=logger,
        )
        return 1

    certificate_event = _certificate_health_event(state, certificate_health)
    certificate_failed = certificate_health.status == "error"
    has_noteworthy = (
        bans
        or audit_keys
        or ssh_failures >= _SSH_FAILURE_THRESHOLD
        or certificate_event is not None
    )
    if not has_noteworthy:
        if certificate_failed:
            log_event(
                logger,
                "XRDP TLS certificate remains unhealthy",
                level=ERROR,
                errors=certificate_health.issue or "unknown certificate error",
            )
            _save_state(_next_state(now, certificate_health))
            return 1
        log_event(logger, "No noteworthy security events")
        _save_state(_next_state(now, certificate_health))
        return 0

    # Determine notification severity.
    # Info-only audit keys (e.g. 'privileged') do not raise to warning —
    # they cover routine admin actions like sudo.
    critical_audit_keys = [k for k in audit_keys if k in _CRITICAL_KEYS]
    certificate_status = certificate_event[0] if certificate_event else "info"
    if audit_critical or certificate_status == "error":
        status = 'error'
    elif bans or critical_audit_keys or certificate_status == "warning":
        status = 'warning'
    else:
        status = 'info'

    # Build details block
    detail_parts: list[str] = []
    if bans:
        detail_parts.append(f"Bans ({len(bans)}):")
        detail_parts.extend(bans)
    if unbans:
        detail_parts.append(f"Unbans ({len(unbans)}):")
        detail_parts.extend(unbans)
    if audit_keys:
        detail_parts.append(f"Audit events: {', '.join(audit_keys)}")
    if ssh_failures >= _SSH_FAILURE_THRESHOLD:
        detail_parts.append(f"SSH auth failures: {ssh_failures}")
    if certificate_event:
        detail_parts.append(certificate_event[2])

    details = '\n'.join(detail_parts)

    # Build subject summary
    summary_parts: list[str] = []
    if bans:
        summary_parts.append(f"{len(bans)} ban{'s' if len(bans) != 1 else ''}")
    if audit_keys:
        summary_parts.append(f"audit: {', '.join(audit_keys)}")
    if ssh_failures >= _SSH_FAILURE_THRESHOLD:
        summary_parts.append(f"{ssh_failures} SSH failures")
    if certificate_event:
        summary_parts.append(certificate_event[1])

    subject = f"Security events: {', '.join(summary_parts)}"
    since_str = since.strftime('%Y-%m-%d %H:%M:%S')

    send_notification_safe(
        notification_configs,
        subject=subject,
        job="security_monitor",
        status=status,
        message=f"Security events detected since {since_str}.",
        details=details,
        logger=logger,
    )

    log_event(logger, "Security monitor check complete",
              status=status, events=', '.join(summary_parts))
    _save_state(_next_state(now, certificate_health))
    return 1 if certificate_failed else 0


if __name__ == '__main__':
    sys.exit(main())
