# Notifications

Setup can persist notification targets for maintenance, security monitoring,
storage operations, CI/CD, and ecosystem update services. Add one or more
targets with repeatable `--notify TYPE TARGET` options.

## Configure targets

```bash
infra_tools setup server_lite fileserver admin \
  --notify webhook https://hooks.example.net/infra \
  --notify mailbox ops@example.com
```

Supported target types are:

- `webhook`: an `http://` or `https://` endpoint receiving a JSON `POST`;
- `mailbox`: an email address delivered through the target's `mail` command
  and local mail transport.

Webhook payloads contain `subject`, `job`, `status`, `message`, `details` when
present, and the sending `hostname`. Successful HTTP responses are 200, 201,
202, or 204. Requests time out after 30 seconds.

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
identify the job. Storage operations send start and completion summaries for
long-running work, while sync and scrub jobs include transfer or repair
details.

## Delivery failures

Notification delivery is best effort. Services log delivery failures and the
underlying maintenance, sync, scrub, or deployment operation generally keeps
its own success or failure result. A missing `mail` command affects mailbox
delivery only; install and configure a local MTA before relying on mailbox
alerts.

Targets are validated before setup or patch runs. Invalid schemes, malformed
mailbox addresses, empty targets, and unknown types fail early:

```bash
infra_tools patch fileserver admin \
  --notify webhook https://hooks.example.net/infra
```

Use `infra_tools info HOST` to confirm that notification configuration is part
of the saved host state. Use `infra_tools cmd HOST` to inspect the reconstructed
command, remembering that notification endpoints may be sensitive.
