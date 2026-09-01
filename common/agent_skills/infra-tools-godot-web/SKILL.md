---
name: infra-tools-godot-web
description: Export, publish, and browser-test Godot web games on an infra-tools-managed VM.
metadata:
  managed-by: infra_tools
---

# Godot web workflow

Use the VM's shared Nginx HTTPS origin on TCP 8443 for static Godot web
exports. The game does not need its own listener or firewall rule. Do not start
a public plain-HTTP server or edit Nginx and UFW directly.

## Publish

1. Run `infra-tools agent doctor --capability development --json` and confirm
   the Godot toolchain is healthy and reports `web_templates: true`.
2. Confirm the repository contains `project.godot` and an appropriate Web
   export preset in `export_presets.cfg`.
3. Run `godot --headless --path . --editor --quit-after 1` when imports need to
   be completed before export.
4. From the project root, run `infra-web publish godot --json`. It derives a
   stable game slug from the project and suppresses the interactive Godot
   progress stream. Pass an explicit slug, `--preset`, or `--debug` only when
   the task requires them. The result reports the URL, elapsed time, artifact
   sizes, and whether it replaced an earlier publication.
5. Replace `GAME` below with the lowercase `game` value returned by `publish`:

   ```bash
   infra-web url GAME
   infra-web doctor GAME
   ```

   Treat the returned URL as authoritative. Do not substitute a local port or
   bypass certificate verification with `curl -k` or an equivalent option.
6. Use the capability-specific browser skill installed on the VM. Prefer
   VM-local Playwright for repeatable canvas and console checks when
   collaboration is unnecessary; use T3 preview for shared, client-origin
   evidence. Confirm that the game canvas initializes without browser console
   errors.

Published games are independent and remain available under their stable URLs.
Use `infra-web list` to inspect them. Remove one only when explicitly requested,
using `infra-web remove GAME --yes`.

Setup enrolls the VM-local CA in the managed user's system and VM-local
Chromium trust stores. A collaborative T3 preview may run on the connected
client and therefore does not necessarily share that trust store. If only the
collaborative preview fails, inspect its snapshot and network error. For an
explicit `ERR_CERT_AUTHORITY_INVALID`, follow the installed T3-capable browser
skill. Client CA enrollment is optional: use VM-local Playwright when
available, or skip the collaborative browser layer and continue VM checks.
Offer the verified public CA URL and fingerprint only when the user wants
preview access restored. If VM-local automation fails trust, report the failed
capability; rerun the saved setup only when the task includes repairing managed
trust. Never suppress HTTPS errors.

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
