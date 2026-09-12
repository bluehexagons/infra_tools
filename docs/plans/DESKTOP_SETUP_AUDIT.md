# Shared desktop setup audit — 2026-09-12

The resize disconnect remains unresolved. The strongest source-level lead is
XRDP's cursor-cache lifecycle, not the shared-session supervisor. Supporting
distribution-packaged Remmina remains the objective. No client downgrade is a
deployment requirement.

## Evidence and limits

The running VM uses Debian XRDP 0.10.6.1-2 and xorgxrdp 1:0.10.5-2, XFCE,
and software rendering. Remmina 1.4.43 runs FreeRDP 3.31.1 on CachyOS.
Native Wayland and XWayland logs both show a successful resize followed by
`Fastpath update Cached Pointer [a] failed`, then automatic reconnection.
The operator also reports reconnection with a 24-bpp profile; there is no
separate trace here verifying its negotiated depth or exact error.

The desktop remains PID 251008 with the same generation across these tests.
During this audit `desktop doctor` reports healthy, no active agent lease,
and geometry 1124×912. Neither XRDP service has a restart policy or drop-ins;
sesman has the intended managed unit with no frontend BindsTo dependency.
No desktop restart, logout, root configuration change, or packet capture was
performed for this audit. Root-only logs beyond the supplied artifacts and
live firewall state were not available for verification.

## Setup map and assessment

| Layer | Managed behavior | Assessment |
| --- | --- | --- |
| Composition | Desktop capability prepares/logout-checks the session, installs desktop/XRDP, applies XFCE/theme settings, then verifies service access | No resize-triggered setup execution |
| Packages | Debian Sid transaction, low-priority source, no recommendations, simulation blocks selected core upgrades/removals | An intentional distro departure; prefer stable/backports when both packages provide required fixes. Local metadata now offers XRDP 0.10.6.1 in Trixie backports, but not the required newer xorgxrdp. Do not blindly downgrade the pair |
| Authentication | Packaged PAM stack, Unix password for human, peer credentials for local sesrun; one owner group | No custom credential transport or resize hook |
| Session policy | MaxSessions=1, Policy=UB, retained disconnected sessions, no default idle timeout | Consistent with persistence; same PID excludes a session restart in captured failures |
| Services | Mask console display managers; decouple sesman from frontend lifetime | Necessary for one shared desktop; no periodic reconnect mechanism |
| Xorg launcher | Direct /usr/lib/xorg/Xorg, per-UID socket environment, trusted relative config path, private log path | Socket/log overrides address prior verified startup failures; preserve for now |
| AppArmor | Per-user socket and shared-memory access, selected render-node access | Prior startup/capture failures justify rules; setup currently overwrites the local include and ignores parser failure, which merits separate preservation/error-handling work |
| Xorg graphics | xrdpdev, explicit modes, optional supported DRM node, glamoregl loaded before xorgxrdp | Retain proven load-order/mode fixes; unsupported options corrected below |
| RDP transport | TLS, bitmap/bulk compression, fast-path both, new cursors, dynamic virtual channels | Fast-path/new-cursor defaults match upstream. Fixed TCP buffers removed. Clipboard remains allowed; drive/audio/RemoteApp blocked |
| Desktop startup | Private D-Bus, desktop identity environment, Python supervisor launches xfce4-session | No RDP connection or pointer-cache ownership; ordinary resize does not invoke teardown |
| Agent controls | Same-UID socket, pause/leases, explicit bounded X11 operations | Idle supervisor does not inject mouse events. Screenshot and geometry operations do not send RDP pointer-cache updates |
| XFCE | Disable Light Locker/display power management, direct notification autostart, clear saved display profiles | Some justified defaults, but overly broad file replacement and unsupported Xfwm settings need follow-up |
| Network protection | RDP ingress policy and AUTHFAIL-based fail2ban | Captured client parser error precedes server socket errors; immediate reconnect succeeds. Not evidence of a ban or listener restart |

## Corrections made in this audit

- Remove `SWCursor=true`: xorgxrdp 0.10.5 does not read that option. It did not
  disable RDP cursor caching or prevent cursor resize failures.
- Replace ignored `UseGlamor=false` with `DRMDevice=""` for software mode.
  The driver otherwise probes its default render node; an empty path makes
  that probe fail and selects software rendering. Explicit supported GPU
  selection remains unchanged. An externally supplied `XORGXRDP_DRM_DEVICE`
  environment variable can override the driver setting; the managed wrapper
  does not set it.
- Restore upstream `DefaultServerLayout="X11 Server"`, preventing another
  Xorg configuration fragment from selecting a different layout.
- Remove fixed 64-KiB TCP buffers. Upstream explicitly recommends allowing
  dynamic OS sizing; no evidence connects those buffers to this parser error.
- Remove ignored `max_idle_time` and `max_disc_time` from xrdp.ini. Actual
  session limits are already configured in sesman.ini.

The previous change removed the ignored `enable_gfx=false` setting. None of
these cleanups is a demonstrated fix for the reported disconnect. The live
session still uses its existing configuration until setup and a new session.

## Direct cursor-cache lead

Source inspection of upstream XRDP v0.10.6.1 shows this sequence:

1. `xrdp_wm_pointer()` assigns a dynamic cache index to `screen->pointer`.
2. Resize's `WMRZ_XRDP_CORE_RESET` calls `xrdp_cache_reset()`, which clears
   the cache structure, including dynamic pointer entries.
3. `WMRZ_XRDP_CORE_RESET_PROCESSED` reloads static pointers 1 and 0.
   This sets `current_pointer` to 0, but does not reset `screen->pointer`.
4. On a subsequent mouse move over the backend screen, `xrdp_wm_mouse_move()`
   compares those fields and can send the old dynamic index through
   `xrdp_wm_set_pointer()` before forwarding the mouse event to Xorg.
5. If that index has not been repopulated, a client with a cleared cache
   receives a cached-pointer reference without a corresponding pointer.

This is a concrete server-side invalidation path, conditional on cursor state
and event ordering. It explains a resize completing before the disconnect
and does not require GFX, native Wayland, or the infra-tools supervisor.
FreeRDP 3.31's cache recreation during reactivation can expose a stale server
reference that earlier clients happened to retain. This is a hypothesis for
the observed trace, not a packet-level confirmation or an assigned upstream
regression. The `[a]` in the error denotes the update type, not the cache index.

Next diagnostic work should instrument XRDP's reset, static-pointer reload,
pointer-definition sends and cached-pointer sends with index and resize state.
Then reproduce with the same distro client. A server regression test should
start with a dynamic screen cursor, resize, and move the mouse before a new
Xorg cursor definition arrives, asserting that every cached reference has a
definition in the new cache. A candidate server fix must reset/redefine the
screen cursor consistently; merely ignoring client errors or clearing all
cursor support would hide the problem. Do not ship a custom XRDP binary until
that regression test and live reproduction validate it.

## Additional cleanup backlog

- XFCE setup rewrites entire power-manager/xfwm4 files and deletes displays.xml
  on every run. Replace this with targeted, idempotent migration preserving
  unrelated user settings. The `/general/Xfwm/Xinerama` property is not an
  established xfwm4 configuration switch; the dark-theme merge also writes
  theme under `/general/Xfwm/theme` rather than `/general/theme`.
- The global `pm-is-supported` stub suppresses warnings by shadowing a command
  for every user. Prefer removing only the known managed stub and tolerating
  harmless messages, after verifying session behavior.
- Xwrapper.config is not in the managed launch path: the launcher directly
  execs the real Xorg binary. Stop describing it as required for this stack;
  retiring the global override needs a migration that preserves other uses.
- The fixed Virtual 3840×2160 is not proof of a required RANDR limit. Compare
  upstream configuration in an isolated session before removing this boot-time
  difference; keep explicit startup modes and the verified module load order.
- Restrict Sid selection to packages actually needing it rather than including
  ordinary X11 utilities in the target-release transaction. The current guard
  rejects a short core-package list, not every possible distro transition.

These are setup quality issues, not demonstrated causes of the cached-pointer
failure. They should not be bundled with an unverified server cursor fix.

## Sources

- [XRDP resize state machine](https://github.com/neutrinolabs/xrdp/blob/v0.10.6.1/xrdp/xrdp_mm.c)
- [XRDP pointer and mouse handling](https://github.com/neutrinolabs/xrdp/blob/v0.10.6.1/xrdp/xrdp_wm.c)
- [XRDP cache reset and static pointer loading](https://github.com/neutrinolabs/xrdp/blob/v0.10.6.1/xrdp/xrdp_cache.c)
- [Upstream XRDP configuration](https://github.com/neutrinolabs/xrdp/blob/v0.10.6.1/xrdp/xrdp.ini.in)
- [xorgxrdp driver option parsing](https://github.com/neutrinolabs/xorgxrdp/blob/v0.10.5/xrdpdev/xrdpdev.c)
- [Upstream Xorg configuration](https://github.com/neutrinolabs/xorgxrdp/blob/v0.10.5/xrdpdev/xorg.conf)
- [FreeRDP cache recreation change](https://github.com/FreeRDP/FreeRDP/pull/13196)
