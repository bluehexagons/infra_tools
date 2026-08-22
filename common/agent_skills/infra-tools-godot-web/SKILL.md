---
name: infra-tools-godot-web
description: Export, publish, and browser-test Godot web games on an infra_tools-managed VM.
metadata:
  managed-by: infra_tools
---

# Godot web workflow

Use the VM's shared Nginx HTTPS origin on TCP 8443 for static Godot web
exports. The game does not need its own listener or firewall rule. Do not start
a public plain-HTTP server or edit Nginx and UFW directly.

## Publish

1. Confirm the repository contains `project.godot` and an appropriate Web
   export preset in `export_presets.cfg`.
2. Run `godot --headless --path . --editor --quit-after` when imports need to
   be completed before export.
3. From the project root, run `infra-web publish godot`. It derives a stable
   game slug from the project. Pass an explicit slug, `--preset`, or `--debug`
   only when the task requires them.
4. Use `infra-web url GAME` as the authoritative externally reachable URL, then
   use `infra-web doctor GAME` to verify the Nginx HTTPS endpoint. Do not infer
   the public URL from a local upstream port or bypass certificate verification
   with `curl -k` or an equivalent option.
5. When Playwright is installed, load the published URL and check that the
   game canvas initializes without browser console errors before declaring a
   browser-facing change complete.

Published games are independent and remain available under their stable URLs.
Use `infra-web list` to inspect them. Remove one only when explicitly requested,
using `infra-web remove GAME --yes`.

Setup enrolls the VM-local CA in the managed user's system and Chromium trust
stores. If browser automation reports a certificate error, use `infra-web ca`
and rerun setup to repair trust; never suppress HTTPS errors.

## Live previews

Prefer static publication for normal Godot exports. If a task genuinely needs
a long-running local preview server, bind it to `127.0.0.1` on an unprivileged
port and use the `infra-tools-web-gateway` skill to expose it through managed
HTTPS with the `godot` profile.

The preview's loopback port remains private. `infra-web` allocates a separate
Nginx HTTPS listener and applies UFW only to that listener; always report the
URL returned by `infra-web`, not the loopback address.

Godot threaded and web GDExtension exports need the managed cross-origin
isolation headers. External assets used by such a game must also satisfy the
browser's cross-origin isolation rules.
