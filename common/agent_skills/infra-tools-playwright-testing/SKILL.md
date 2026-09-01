---
name: infra-tools-playwright-testing
description: Browser-test web applications with the managed VM-local Playwright installation on an infra-tools agent VM without T3 Code preview guidance.
metadata:
  managed-by: infra_tools
---

# VM-local Playwright testing

This VM has managed Playwright and no provisioned T3 Code preview workflow.
Use Playwright directly for browser work; do not wait for or attempt to install
a collaborative preview.

## Readiness and origin

Before the first browser action, run:

```bash
infra-tools agent doctor --capability browser --json
```

Proceed only when `healthy` is true. Use the stable `issues` list and primary
`remediation` code when it is not. A missing capability or unhealthy launcher
is a coverage gap, not permission to install another browser stack, bypass the
managed MCP wrapper, or expose a service.

Playwright and its Chromium traffic originate on the VM. Keep development
servers on loopback and use their reported URL. This is usually the best path
for repeatable DOM interaction, console/network inspection, browser-engine
verification, canvas testing, and local Vite or game previews.

## Interaction and evidence

Confirm rendered content rather than relying on navigation success alone. For
WebAssembly or WebGL, allow one bounded startup interval after document load.
For canvas applications, map controls from a screenshot and use the managed
bounded coordinate input tool; coordinates are viewport-relative CSS pixels.
Recapture after resizing. If a WebGL screenshot is still empty after the
launcher's one-second settle delay, wait another second and retry once.

Browser-process `ReadPixels` warnings emitted during capture are not page
console errors. Use the console tool to assess application failures.

Generated evidence defaults to the private, bounded
`~/.local/state/infra_tools/playwright-mcp` directory. Omit `filename` for
routine evidence; name an artifact only when the user requested it as a
workspace deliverable. Avoid passwords, tokens, private response bodies, and
unrelated user data.

## HTTPS and client access

The VM-local browser uses the VM trust store. Never disable certificate
verification. If managed HTTPS fails trust in Playwright, report the unhealthy
runtime or trust layer and rerun saved setup only when repair is in scope.

Use the `infra-tools-web-gateway` skill only when a task requires another
client to reach a static build or loopback service. Publishing changes external
reachability and is not needed merely to let VM-local Playwright test an app.
