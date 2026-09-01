---
name: infra-tools-browser-testing
description: Browser-test web applications on an infra-tools agent VM that has both T3 Code collaborative previews and managed VM-local Playwright.
metadata:
  managed-by: infra_tools
---

# T3 preview and Playwright

This VM has two browser surfaces with different strengths and network origins.
Choose deliberately; T3 preview is not a mandatory first step when collaboration
is not part of the task.

## Choose the browser

Prefer VM-local Playwright when the task needs repeatable headless interactions,
DOM/console/network inspection, loopback access, canvas input, or browser-engine
verification that does not need to be shared live with the user. It remains
available when the T3 application is closed.

Prefer the T3 collaborative preview when the user should watch or participate,
the requested evidence must appear in the shared UI, or the task specifically
tests the connected client's routes or certificate trust. That browser runs in
the connected client's context, not the VM's.

When either surface is equally suitable, an already attached preview is useful
for collaboration. Otherwise Playwright is the dependable default. State which
surface and network origin produced the result when that distinction matters.

## Use managed Playwright

Before the first VM-local browser action, run:

```bash
infra-tools agent doctor --capability browser --json
```

Use Playwright only when `healthy` is true. Follow the stable `issues` and
`remediation` fields when it is not; do not install another browser stack or
mutate the managed launcher. `stale_processes` requires restarting the affected
agent session.

Keep development servers on loopback. Playwright originates on the VM, so it
can reach VM loopback and uses the VM's DNS, routes, source IP, and trust store.
Generated evidence belongs in the private, bounded
`~/.local/state/infra_tools/playwright-mcp` directory by default. Omit
`filename` unless the user requested a workspace deliverable.

For canvas applications, map controls from a screenshot and use the bounded
coordinate input tool. Coordinates are viewport-relative CSS pixels; recapture
after resizing. The launcher waits one second after actions. For a still-empty
WebGL capture, wait another second and retry once. Browser-process `ReadPixels`
warnings are not page console errors.

## Use the collaborative preview

Call `preview_status` first. If there is no automation-capable tab, call
`preview_open` once. Do not repeatedly reopen or poll: the T3 application may
simply be closed or minimized. A hidden tab may still accept navigation while
snapshot or recording capture is unavailable; attempt one snapshot before
classifying coverage.

Preview absence is a normal fallback condition. Continue immediately with
healthy Playwright when VM-origin testing fits the task. Do not treat the
closed T3 application as an application failure.

An `environment-port` target rewrites the port onto the environment connection
host; it is not a tunnel to VM loopback. If a verified loopback server leaves
the preview at `about:blank` with no network entry, use Playwright for VM-origin
coverage. Publish through the managed `infra-tools-web-gateway` only when
client-visible access is itself in scope; do not rebind the server or widen the
firewall solely for automation.

Opening a tab or seeing the requested URL in status is not proof of rendering.
Confirm visible content or a snapshot. For WebAssembly/WebGL, allow one bounded
startup interval beyond document load before judging the application frame.

## Certificate errors are optional to repair

Only treat an explicit `net::ERR_CERT_AUTHORITY_INVALID` preview network entry
as a client trust error. Do not require the user to enroll the VM CA to finish
an otherwise testable task. Route browser work to healthy VM-local Playwright,
continue server and HTTP checks, and report that collaborative client-origin
coverage was skipped. Never use `curl -k`, ignore HTTPS errors, or weaken TLS.

If the user wants collaborative preview access restored, run:

```bash
infra-web ca
```

Give the user the reported enrollment URL and SHA-256 fingerprint. Have them
compare that fingerprint with the downloaded public certificate before trust:

- Debian-based Linux: place the verified `.crt` in
  `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`.
- Windows current user: run
  `certutil -user -addstore -f Root .\infra-tools-ca.crt`.
- ChromeOS: import the verified certificate under certificate-manager
  **Authorities**; managed devices require an authorized administrator.
- Android: use the device's CA certificate installation settings; embedded apps
  may still reject user-added roots.

Installing a CA changes client security state, so the user performs that step.
Restart T3 Code after enrollment, recheck preview status, and retry the existing
tab. If they decline, keep using Playwright or skip the affected preview-only
operation.

## Evidence and safety

Test the application- or gateway-reported URL, not a guessed port. Capture only
the interactions, console failures, and screenshots needed for the handoff.
Avoid passwords, tokens, private response bodies, and unrelated user data.
Never infer that client-preview failure means a VM service is down; report the
origin that passed and the origin that could not be exercised.
