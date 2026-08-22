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

Webhook payloads use a versioned common envelope containing `schema_version`,
`event_type`, `state` (`firing`, `resolved`, or `success`), `dedup_key` when
available, `subject`, `job`, `status`, `message`, `details` when present, and
the sending `hostname`. Optional `actions` and producer-specific `data` carry
operator guidance and machine-readable facts. Security-monitor `data` includes
the collection `window`, event counts, source-health state, SSH source/user/
method summaries, and audit evidence. Consumers should route and deduplicate
using the typed fields rather than parsing the human-readable message.
Successful HTTP responses are 200, 201, 202, or 204. Requests time out after
30 seconds.

Treat webhook URLs as credentials if they contain tokens or query-string
secrets. Keep them out of shell history and shared command output, and prefer a
dedicated endpoint with narrowly scoped access. Notification targets are setup
configuration, not workspace passwords.

## What sends notifications

Configured targets are reused by:

- APT, Node.js, Ruby, uv, and Gogs update jobs;
- restart checks, security monitoring, and cleanup maintenance;
- sync, parity, and storage-operation summaries; and
- CI/CD executor success and failure reporting.

Messages include a status such as `good`, `info`, `warning`, or `error` and
identify the job. Routine scheduled-operation starts and successful sync,
scrub, Node update, and CI/CD runs are retained in local logs by default;
failure, warning, repair, and recovery events remain externally actionable.
Producers can opt into success delivery for workflows that need completion
proof.

Security-monitor notifications are summarized for people as a time window,
overall status, categorized findings, evidence, and suggested actions. Routine
sudo/privileged-execution audit hits and fail2ban ban expirations do not notify
by themselves. SSH failures are aggregated by source, account, and method;
fail2ban bans contain the source IP and jail. Protected-file audit events carry
paths, actors, operations, and executables where auditd provides them. PAM/
faillock account lockouts are reported as warning-level account events.

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
