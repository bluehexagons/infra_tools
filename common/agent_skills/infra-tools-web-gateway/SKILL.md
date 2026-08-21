---
name: infra-tools-web-gateway
description: Publish or safely expose loopback web services through an infra_tools-managed HTTPS gateway.
metadata:
  managed-by: infra_tools
---

# Managed HTTPS gateway

Use `infra-web` for HTTPS URLs on this VM. Never bind a development service to
`0.0.0.0`, open UFW directly, write Nginx configuration, or disable TLS
verification.

## Choose the hosting mode

- For a Godot web export, use `infra-web publish godot` and the
  `infra-tools-godot-web` skill. Static games do not need dedicated ports.
- For a live HTTP or WebSocket service, bind the service to `127.0.0.1` or
  `::1` on an unprivileged port, then register a managed forward.

## Live forwards

Create a forward after its loopback service is ready:

```bash
sudo infra-web forward add NAME --listen auto --to 127.0.0.1:PORT
```

Add `--profile godot` for a Godot preview that needs secure-context and
cross-origin isolation headers. The command chooses a permitted HTTPS port,
applies the VM's existing access-source policy, validates Nginx, reconciles
UFW, and prints the URL.

Use `infra-web forward list`, `infra-web doctor NAME`, and `infra-web ca` for
inspection. Remove a route when the associated service is no longer intended
to be reachable:

```bash
sudo infra-web forward remove NAME
```

Do not proxy databases, SSH, metadata endpoints, or another user's service.
Treat adding or removing a forward as an external exposure change and keep it
within the user's requested scope.
