# Notifications

Setup can persist notification targets for maintenance, security monitoring,
storage operations, CI/CD, and ecosystem update services. Add one or more
targets with repeatable `--notify TYPE TARGET` options.

## Configure targets

```bash
infra-tools setup server_lite fileserver admin \
  --notify webhook https://hooks.example.net/infra \
  --notify mailbox ops@example.com
```

Supported target types are:

- `webhook`: an `http://` or `https://` endpoint receiving a JSON `POST`;
- `mailbox`: an email address delivered through the target's `mail` command
  and local mail transport.

Webhook payloads use schema version 2 and deliberately separate event metadata,
operator-facing content, and producer-specific facts:

```json
{
  "schema_version": 2,
  "event": {
    "type": "security.source_health",
    "state": "resolved",
    "status": "info",
    "deduplication_key": "security_monitor:source-health"
  },
  "operator": {
    "subject": "Security source recovered",
    "job": "security_monitor",
    "system": "fileserver",
    "what_happened": "Auditd is readable again",
    "suggested_actions": ["No action is required"],
    "details": ""
  },
  "data": {}
}
```

Together, the `event` and `operator` objects mirror the mailbox's subject, job,
status context, system, event state, explanation, suggested actions, and details
in stable fields. Empty actions and details are represented consistently, so
consumers can render the REST notification directly without parsing prose.
Route and deduplicate using the typed `event` fields. Security-monitor `data`
includes the collection `window`, event counts, source-health state, SSH
source/user/method summaries, and audit evidence.
Successful HTTP responses are 200, 201, 202, or 204. Requests time out after
30 seconds.

Treat webhook URLs as credentials if they contain tokens or query-string
secrets. Keep them out of shell history and shared command output, and prefer a
dedicated endpoint with narrowly scoped access. Notification targets are setup
configuration, not workspace passwords.

## What sends notifications

Configured targets are reused by:

- APT, Node.js, uv, and Gogs update jobs;
- restart checks, security monitoring, and cleanup maintenance;
- sync, parity, and storage-operation summaries; and
- CI/CD executor success and failure reporting.

Messages include a status such as `good`, `info`, `warning`, or `error` and
identify the job. Routine scheduled-operation starts and successful sync,
scrub, Node update, and CI/CD runs are retained in local logs by default;
failure, warning, repair, and recovery events remain externally actionable.
Producers can opt into success delivery for workflows that need completion
proof. Cleanup storage-pressure warnings are sent on threshold transitions and
once again when pressure recovers, rather than on every maintenance run.

Security-monitor notifications are summarized for people as a time window,
overall status, categorized findings, evidence, and suggested actions. Routine
sudo/privileged-execution audit hits and fail2ban ban expirations do not notify
by themselves. SSH failures are aggregated by source, account, and method;
fail2ban bans contain the source IP and jail. Protected-file audit events carry
paths, actors, operations, and executables where auditd provides them. PAM/
faillock account lockouts are reported as warning-level account events.

Audit events produced during a recorded `infra-tools` setup window are treated
as expected maintenance and excluded from later security notifications. The
setup success or failure notification remains the record of that work, while
audited changes after the setup window are still reported. Audit notification
subjects and summaries describe the affected control (accounts, administrator
access, SSH configuration, or kernel modules) and explicitly distinguish
reviewable evidence from proof of compromise.

The monitor also reports an unavailable auditd, fail2ban, or SSH journal source
as a monitoring-health event only when the problem starts (and again when it
recovers). It holds the event cursor while collection is incomplete so events
are not silently skipped. A missing optional security component remains quiet.

## Delivery failures

Notification delivery is best effort. `send_notification_safe` returns whether
all configured targets accepted the event and logs incomplete delivery; the
underlying maintenance, sync, scrub, or deployment operation keeps its own
success or failure result. A missing `mail` command affects mailbox delivery
only; install and configure a local MTA before relying on mailbox alerts.

Targets are validated before setup or patch runs. Invalid schemes, malformed
mailbox addresses, empty targets, and unknown types fail early:

```bash
infra-tools patch fileserver admin \
  --notify webhook https://hooks.example.net/infra
```

Use `infra-tools info HOST` to confirm that notification configuration is part
of the saved host state. Use `infra-tools cmd HOST` to inspect the reconstructed
command, remembering that notification endpoints may be sensitive.
