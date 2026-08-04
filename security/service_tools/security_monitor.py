#!/usr/bin/env python3
"""
Security Event Monitor

Checks security logs for notable events and sends notifications via the
configured infra_tools notification targets. Runs every 15 minutes.

Event sources (where installed):
  - fail2ban: ban/unban events from /var/log/fail2ban.log
  - auditd: identity, sudoers, SSH config, module, and privileged-exec events
  - SSH: failed authentication attempts from the system journal

Severity rules:
  error   — auditd detected writes to identity/sudoers/SSH-config files or
             kernel module loads (potential system compromise indicators)
  warning — fail2ban banned an IP address
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
import tempfile
from datetime import datetime, timedelta
from logging import WARNING

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger, log_event
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.validation import validate_filesystem_path

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
    state_dir = os.path.dirname(_STATE_FILE)
    os.makedirs(state_dir, exist_ok=True)
    temporary_path = ''
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=state_dir,
            prefix=f'.{os.path.basename(_STATE_FILE)}.',
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, _STATE_FILE)
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


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
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    log_event(logger, "Starting security monitor check")

    notification_configs = load_notification_configs_from_state(logger)
    if not notification_configs:
        log_event(logger, "No notification targets configured, skipping")
        _save_state({'last_run': datetime.now().isoformat()})
        return 0

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

    has_noteworthy = bans or audit_keys or ssh_failures >= _SSH_FAILURE_THRESHOLD
    if not has_noteworthy:
        log_event(logger, "No noteworthy security events")
        _save_state({'last_run': now.isoformat()})
        return 0

    # Determine notification severity.
    # Info-only audit keys (e.g. 'privileged') do not raise to warning —
    # they cover routine admin actions like sudo.
    critical_audit_keys = [k for k in audit_keys if k in _CRITICAL_KEYS]
    if audit_critical:
        status = 'error'
    elif bans or critical_audit_keys:
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

    details = '\n'.join(detail_parts)

    # Build subject summary
    summary_parts: list[str] = []
    if bans:
        summary_parts.append(f"{len(bans)} ban{'s' if len(bans) != 1 else ''}")
    if audit_keys:
        summary_parts.append(f"audit: {', '.join(audit_keys)}")
    if ssh_failures >= _SSH_FAILURE_THRESHOLD:
        summary_parts.append(f"{ssh_failures} SSH failures")

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
    _save_state({'last_run': now.isoformat()})
    return 0


if __name__ == '__main__':
    sys.exit(main())
