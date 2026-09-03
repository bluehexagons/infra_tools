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
    "id": "629ae4a98e8b4e55aec19fd969666a0e",
    "occurred_at": "2026-09-03T10:00:00+00:00",
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
in stable fields. Each generated notification has a random stable event ID and
UTC occurrence time. Retries reuse the same ID, which is also sent in the
`X-Infra-Tools-Event-ID` header, so receivers can make delivery idempotent.
Empty actions and details are represented consistently, so consumers can render
the REST notification directly without parsing prose. Route and deduplicate
using the typed `event` fields. Security-monitor `data` includes the collection
`window`, event counts, source-health state, SSH source/user/method summaries,
and audit evidence.

Any 2xx HTTP response is successful. Transient connection failures and HTTP
408, 425, 429, 500, 502, 503, and 504 responses receive two bounded retries;
numeric `Retry-After` values are honored up to 30 seconds. Requests time out
after 30 seconds per attempt. Redirects are never followed, because forwarding
an authenticated notification to a different URL could disclose credentials.

Treat webhook URLs as credentials if they contain tokens or query-string
secrets. Keep them out of shell history and shared command output, and prefer a
dedicated endpoint with narrowly scoped access. Notification targets are setup
configuration, not workspace passwords. Setup summaries show only the webhook
scheme, host, and port (or only a mailbox domain); endpoint paths, queries,
fragments, and mailbox local parts are redacted. Reconstructed setup commands
still contain the configured target because they must remain executable.
Identical repeated targets are normalized and notified only once.

For the optional infra-tools web-panel ingest API, put its URL-safe bearer
token in the webhook URL fragment:

```bash
infra-tools patch sender.example agent \
  --notify webhook \
  'https://panel.example/api/v1/notifications#TOKEN_FROM_PANEL_HOST'
```

Fragments are never sent as part of an HTTP URL. infra-tools validates this
form as HTTPS-only, removes the fragment, and places the token in the
`Authorization: Bearer ...` header. Other webhook URLs continue to work as
before. The panel retains one record for repeated delivery attempts carrying
the same event ID and reports duplicate retries as already accepted. See
[Minimal web panel](WEB_PANEL.md#notification-ingest-api) for API enablement,
token storage, rotation, limits, and retention.

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

Notification delivery is best effort. After the bounded webhook retries,
`send_notification_safe` returns whether all configured targets accepted the
event and logs incomplete delivery; the underlying maintenance, sync, scrub,
or deployment operation keeps its own success or failure result. Permanent HTTP
failures, TLS failures, and mailbox failures are not retried. A
missing `mail` command affects mailbox delivery only; install and configure a
local MTA before relying on mailbox alerts.

Saved targets are revalidated by scheduled jobs. A corrupt target is ignored
and logged without disabling other valid targets from the same saved setup.

Targets are validated before setup or patch runs. Invalid schemes, malformed
mailbox addresses, empty targets, and unknown types fail early:

```bash
infra-tools patch fileserver admin \
  --notify webhook https://hooks.example.net/infra
```

Use `infra-tools info HOST` to confirm that notification configuration is part
of the saved host state. Use `infra-tools cmd HOST` to inspect the reconstructed
command, remembering that notification endpoints may be sensitive.
