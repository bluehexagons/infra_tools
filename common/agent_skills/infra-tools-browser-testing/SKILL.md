---
name: infra-tools-browser-testing
description: Browser-test web applications on an infra-tools agent VM with a collaborative T3 preview or the optional managed Playwright fallback.
metadata:
  managed-by: infra_tools
---

# Browser testing on an agent VM

## Choose the browser path

Prefer the collaborative T3 preview when it is attached to the current
session. It keeps navigation, interaction, screenshots, and failures visible
to the connected user.

For an SSH-only session, verify the optional VM-local browser before relying on
it:

```bash
infra-tools agent doctor --capability browser --json
```

Use the managed browser integration only when that check succeeds. A missing
capability is expected unless setup requested `--browser-automation
playwright`; report the missing capability instead of installing an unrelated
browser stack or exposing a browser service.

## Test a project

Keep development servers on loopback. For an external HTTPS URL, publish the
static build or expose the loopback server with the `infra-tools-web-gateway`
skill when that capability is installed.

Test the URL reported by the application or `infra-web`, not a guessed port.
Capture a small set of user-visible interactions, console failures, and a
screenshot when it helps the handoff. Avoid recording passwords, tokens,
private response bodies, or unrelated user data.

## HTTPS trust

Never bypass TLS verification. VM-local Playwright and Chromium use the CA
trust enrolled by setup. A collaborative preview may run on the connected
client and therefore use a different trust store. For a URL published by the
managed `infra-web` gateway, if only that client reports a certificate error,
run:

```bash
infra-web ca
```

Use its enrollment URL and fingerprint on the client. If VM-local automation
fails trust instead, report the failed capability. Rerun the saved setup to
repair the managed VM trust store only when the task includes that repair.
For any other HTTPS origin, follow that origin's documented trust process.
