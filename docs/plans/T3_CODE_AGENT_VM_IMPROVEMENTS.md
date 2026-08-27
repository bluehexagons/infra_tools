# T3 Code Agent VM Improvement Plan

Status: active implementation; phases 1 through 3 are code-complete as of
2026-08-27, with disposable-VM deployment validation still pending.

## Objective

Make infra-tools-managed T3 Code VMs easier to operate during long agent
sessions without turning the base profile into an implicit collection of every
runtime and automation tool. Preserve the existing user-scoped service,
credential, repository, HTTPS, and pairing boundaries.

## Evidence and design decisions

A representative active `agent_code_vm` passed both the T3 Code and Playwright
doctor checks while operating with 1.8 GiB of guest memory, 1 GiB of used swap,
and a T3 service memory peak above 3.5 GiB. Its 32 GiB root filesystem was 73%
used. The largest rebuildable or bounded areas included a 3.4 GiB npm cache,
1.3 GiB of Playwright browser data, and more than 600 MiB of T3 logs.

The T3 client also supplied collaborative preview automation in the same
session. A second VM-local Playwright runtime is still useful for SSH-only
sessions, standalone Codex or OpenCode, and reproducible headless checks, but
it does not need to be installed on every T3-focused VM.

These observations lead to four rules:

1. Service readiness and operating headroom are separate diagnostic results.
2. T3-native preview is the preferred interactive path; Playwright remains an
   explicit `--browser-automation playwright` fallback.
3. Automated cleanup may touch only allowlisted, rebuildable, or clearly
   rotated data. Vendor-managed active versions and agent session state are
   not generic caches.
4. Concurrent tasks need repository and port isolation without overwriting a
   dirty checkout.

## Delivery phases

### Phase 1: profile and diagnostic baseline

Completed in `6c050dc`.

- Remove Playwright from the implicit `agent_code_vm` defaults while retaining
  the existing explicit browser-automation flag.
- Add a stable `agent doctor --capability host` text and JSON result covering
  memory, swap, disk, bounded agent storage, T3 cgroup pressure, maintenance
  timers, and pending reboots.
- Keep advisory capacity issues as warnings; fail only for critical filesystem
  pressure or a recorded maintenance failure.
- Extend the managed T3 skill to choose native preview when available and the
  explicit Playwright fallback for SSH-only sessions.

### Phase 2: bounded storage lifecycle

Implemented with conservative ownership boundaries. npm `_npx` workspaces and
numbered T3 log rotations are now bounded by the user maintenance job.
Playwright already records every consuming installation in its shared `.links`
registry and performs reference-aware garbage collection; infra-tools will not
add a competing directory-deletion mechanism that could remove another
client's browser. Codex standalone releases remain diagnostic-only vendor
rollback state.

- Bound stale npm `npx` workspaces independently of npm's content cache.
- Prune only rotated T3 provider and trace logs, retaining current log files
  and recent diagnostic history.
- Preserve Playwright's reference-aware shared-browser lifecycle and verify its
  garbage collection during pinned version upgrades.
- Report extra Codex standalone releases without deleting vendor-managed
  rollback state automatically.
- Add dry-run and real-VM coverage for every cleanup boundary.

### Phase 3: task isolation and operator evidence

Implemented with a local managed-worktree lifecycle, redacted JSON support
snapshot, and focused workspace, deployment-smoke, and VM-triage skills. Port
allocation stays with the existing `infra-web preview start` and `forward add
--listen auto` paths so the VM has one source of truth for loopback processes,
HTTPS listeners, UFW policy, and cleanup.

- Add managed per-task Git worktree creation, listing, status, and explicit
  cleanup with safe repository and branch validation.
- Allocate loopback preview ports without exposing them; use the existing
  HTTPS gateway when a user requests a shared preview.
- Add a redacted support-bundle command composed from the stable doctor
  results, versions, service state, and bounded logs.
- Install focused workspace, deployment-smoke, and VM-triage skills alongside
  the existing T3 and HTTPS-gateway skills.

### Phase 4: disruptive maintenance and version policy

- Add an agent-host maintenance hold/drain marker and teach automatic restart
  policy to defer for active agent, build, worktree, and terminal-multiplexer
  workloads.
- Run the composite readiness audit after reboot or a deliberate agent update.
- Finish desired-versus-observed version channels and artifact-level rollback
  for agent tools where upstream distribution contracts support them.

Phase 4 changes host restart and vendor-version policy and therefore remains a
separate implementation slice requiring disposable-VM validation. It should
reuse the existing restart and update mechanisms rather than introduce a
parallel scheduler.

## Acceptance criteria

- A new `agent_code_vm` does not download Chromium unless the operator supplies
  `--browser-automation playwright`.
- Existing saved setups that explicitly selected Playwright retain it.
- Host diagnostics never read or emit credential contents, repository file
  contents, prompts, or agent conversation/session contents.
- Storage cleanup rejects symlinks and paths outside the configured user's
  home, preserves active vendor versions, and has useful dry-run output.
- Workspace cleanup cannot remove the main checkout, a dirty worktree, or an
  unmerged branch without a separate explicit destructive authorization.
- Unit tests pass and each mutation-heavy phase receives a real Debian VM smoke
  test before being considered complete.
