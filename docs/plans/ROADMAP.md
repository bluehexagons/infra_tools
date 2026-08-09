# Project Roadmap

Status: active planning guidance.

This roadmap is intentionally opinionated. `infra_tools` already supports a
wide range of setup and operations tasks; the next releases should complete
the safety and recovery loops around those tasks before adding more operating
systems, desktop applications, or service-specific installers.

## Product direction

The project should become a small, dependable infrastructure reconciler for
Debian and Proxmox environments. A successful operation should mean more than
"the commands ran": the requested state was validated, the change was applied,
the result was verified, and a documented recovery path remains available.

Priorities are ordered by these principles:

1. A failed operation must stop and preserve or restore the last working state.
2. One declaration should drive manual setup, redeploys, and webhook CI/CD.
3. Every destructive or connectivity-sensitive apply path needs a preview and
   rollback path.
4. Saved configuration should support fleet-wide audit and drift detection.
5. New providers and platforms should reuse these guarantees rather than add
   parallel execution models.

## Verification snapshot (2026-08-09)

The ordering remains justified by the current implementation:

- required command failures now raise from `remote_utils.run(check=True)`;
  caller classification and recovery orchestration remain incomplete;
- full setup removes existing managed services before replacement steps run;
- manifest deployment stops services and deletes the current tree before the
  replacement build, while exhausted health checks only warn;
- persistent JSON state/configuration now uses the shared atomic writer, but
  corrupt-state readers still fall back permissively; and
- privileged shared SSH command builders still accept first-seen host keys.

The manifest environment-key injection finding is resolved. CI now tests
Python 3.10, 3.12, and 3.14, and `make compile` propagates compilation failures.
Those completed items should remain regression coverage, not active roadmap
work.

The best next work packets are:

1. Complete the `remote_utils.run()` caller inventory and define strict versus
   best-effort contracts (the strict helper slice is now landed).
2. Decide whether to redesign or remove the currently unused
   `lib/transaction.py` framework; do not build a parallel transaction layer.
3. Replace permissive corrupt-state fallbacks with schema/version checks and
   actionable remediation, then define durable operation markers.
4. Stage manifest releases and make health-check failure block activation and
   restore the previous release.
5. Replace automatic SSH first-use trust with explicit enrollment before
   privileged setup/deploy operations.

## P0: Transactional execution and state

The first priority is resolving the execution and partial-apply risks captured
in [the architectural risk review](ARCHITECTURAL_RISK_REVIEW_2026-08-07.md).
The detailed implementation plan is in
[Transactional execution and reconciliation](TRANSACTIONAL_EXECUTION.md).

Required outcomes:

- command helpers have explicit fail-fast and best-effort contracts;
- setup stages service changes and does not remove a working service until its
  replacement is ready;
- deployment health checks gate success and restore the previous release when
  activation fails;
- persistent state is written atomically and corrupt state produces actionable
  errors instead of silent defaults; and
- privileged SSH paths use verified host keys rather than automatic first-use
  trust.

This work is the foundation for every later apply or rollback feature.

## P1: One manifest-driven deployment platform

The direct deployment and webhook paths should converge on `infra.json` as the
shared application model.

The sequence should be:

1. Implement [deploy secrets and optional components](DEPLOY_SECRETS.md).
2. Make component health failures block activation and trigger rollback.
3. Teach [CI/CD to reuse manifests](CICD_MANIFEST_REUSE.md).
4. Add component-level change detection and artifact reuse after correctness is
   shared across both entry points.

The desired result is one definition for components, build inputs, secrets,
runtime users, health checks, routing, and persistent data. Repository-authored
scripts may remain an escape hatch, but they should not be the primary model.

## P1: Plan, audit, and drift detection

`--dry-run` is useful, but it is not a desired-versus-observed state diff. Add
a read-only planning layer before expanding mutation features:

- `infra_tools plan HOST` reports proposed changes and unavailable facts;
- `infra_tools audit PATTERN` checks saved hosts without changing them;
- plans use stable change categories and meaningful exit codes;
- text output remains human-friendly while JSON output is consistent enough
  for CI and external tooling; and
- the applied result is verified against the same observations used by the
  plan.

Start with services, managed files, packages, and deployments. Avoid promising
a universal package-level diff until the existing setup steps expose enough
structured state.

The Proxmox-specific facts, update preflights, and storage checks for this layer
are detailed in the
[Proxmox setup and maintenance audit](PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md).

The CLI-only coding-host slice is detailed in the
[agent host and maintenance audit](AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md).
Its P1 work adds verified/versioned agent-tool updates, workload-aware restart
holds and maintenance windows, and agent/timer health to the same audit surface.
It should reuse the transactional execution and observed-state contracts rather
than introduce agent-specific apply machinery.

The RDP-capable coding-desktop slice is detailed in the
[RDP desktop agent audit](DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md). It
adds RDP exposure and certificate policy, supported session lifecycle,
version-aware configuration, and live desktop smoke tests to those shared
contracts.

## P2: Recovery as a first-class workflow

Backup creation without tested restoration is incomplete. Build operator-facing
recovery commands for the assets the project already manages:

- restore, retention, and scheduled verification for Proxmox backups;
- application and database `backup`, `restore`, and `rollback` operations;
- a recovery inventory showing available snapshots, backups, and releases; and
- documented destructive confirmations and dry runs for every restore path.

Restore verification should be designed before adding more backup backends.
The Proxmox discovery, retention, verification-job, and isolated-restore slice
is scoped in the
[Proxmox setup and maintenance audit](PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md).

## P2: Safe network apply and rollback

The existing network inventory and Proxmox renderer are the right boundary for
a controlled apply workflow. The first mutation path should:

1. validate management sources and current reachability;
2. save the exact current firewall artifacts;
3. install a timed automatic rollback before applying changes;
4. apply and verify management connectivity; and
5. require explicit confirmation before cancelling the rollback.

Switch, router, and cloud adapters should follow only after the Proxmox apply
contract proves this safety model.

## P3: Extensibility and release quality

Once the lifecycle work is established:

- isolate malformed plugins so one optional capability cannot break unrelated
  commands;
- document a stable provider/adapter contract for network and secret backends;
- add packaging installation smoke tests and explicit package metadata;
- add linting, incremental type checking, and a measured coverage floor; and
- consider another Debian-like distribution only when its CI and live-test
  expectations can be stated precisely.

Broad operating-system support is not currently worth the extra branching in
security, package, service, and networking behavior.

## Small improvements to land continuously

Small, well-contained fixes should not wait for a larger phase. Good follow-ups
include plugin import fault isolation, consistent `--json` support for
read-only commands, a local package-install smoke test, and auditing remaining
non-JSON configuration writes for atomic replacement and permissions.

## Deliberately deferred

Until P0 and P1 are substantially complete, avoid prioritizing:

- additional browsers, desktop environments, and language installers;
- broad non-Debian support;
- multiple network providers before safe Proxmox apply exists; and
- a generalized public plugin SDK before startup isolation is in place.

These features increase surface area without improving the reliability of the
core workflows operators already depend on.
