# Transactional Execution and Reconciliation

Status: partially implemented; durable operation state and broader setup
reconciliation remain highest priority.

This plan turns setup and deployment from a sequence of mostly independent
commands into an operation with explicit preparation, activation, verification,
and recovery phases. It addresses ARCH-01, ARCH-03, ARCH-05, ARCH-06, and
ARCH-08 from the [architectural risk review](ARCHITECTURAL_RISK_REVIEW_2026-08-07.md).

## Goals

- Stop immediately when a required command fails.
- Preserve the last working service or release until replacement activation.
- Make partial state visible and recoverable after interruption.
- Use the same validation result for planning and post-apply verification.
- Keep best-effort maintenance operations possible, but make that choice
  explicit at each call site.

## Verified implementation baseline (2026-08-19)

- `lib.remote_utils.run(check=True)` now raises `CommandExecutionError` with a
  bounded stderr diagnostic; callers that intentionally inspect failure use
  explicit `check=False`.
- `remote_setup.py` no longer removes all managed services before setup steps.
- `DeploymentOrchestrator.deploy_manifest()` builds and validates a sibling
  release before stopping app-scoped services. Failed activation restores the
  prior release and generated unit files.
- Manifest health polling accepts only 2xx responses and rejects an unhealthy
  release. Stable ports, app-scoped build identities, SQLite pre-deploy backups,
  and deployment serialization are implemented.
- Nginx deployment files are snapshotted and restored after failed validation;
  managed files use atomic replacement and unmanaged same-name sites are not
  overwritten.
- A shared `lib.atomic_io.write_json_atomic()` now protects machine/setup state,
  caches/history, webhook and deploy-target configuration, deployment/release
  metadata, host/network inventories, Cloudflare state, remote argument files,
  and Gogs admin credentials. Its tests cover replacement interruption and
  restrictive permissions.
- Readers still fall back on corrupt JSON in several paths; schema versions and
  actionable remediation remain open work.
- Shared SSH/SCP/rsync builders use `StrictHostKeyChecking=yes` with the
  workspace enrollment file. The Proxmox guest helper does not yet pass that
  file, and build-server deployment targets are still populated from an
  unauthenticated `ssh-keyscan`.

There is also an existing `lib/transaction.py` and `lib/operation_log.py` pair,
but production apply paths do not use the transaction manager. Its state is
in-memory, `execute()` does not trigger rollback, and continue-on-error can
report success after a failed step. It must be deliberately redesigned and
adopted or removed; this project should not introduce a second competing
transaction abstraction.

## Phase 0: Contract and primitive convergence

Before changing broad execution behavior:

1. Inventory and classify every `remote_utils.run()` caller as required,
   optional, probe, or cleanup, including its current return-code handling.
2. Decide the fate of `lib/transaction.py` and `lib/operation_log.py` against
   the interruption-recovery requirements below. Remove unused pieces that do
   not fit the chosen design.
3. Define the durable operation-marker schema, ownership, location, and
   recovery behavior before wiring setup or deploy to it.
4. Add fault-injection tests at the orchestration boundary, not only unit tests
   of transaction primitives.

## Phase 1: Execution contracts

Split the ambiguous `lib.remote_utils.run()` behavior into explicit contracts.
The preferred shape is a strict default that raises a project-specific command
error containing the argv, return code, and bounded stderr. Callers that can
legitimately continue should request a result-returning best-effort mode and
inspect it.

Migration requirements:

- inventory every `run()` caller before changing the helper;
- classify failures as required, optional, probe, or cleanup;
- keep secrets out of command displays and exception messages;
- avoid shell execution when an argv form is sufficient; and
- add regression tests for failure propagation through complete setup steps.

Do not change the helper and assume all callers want strict behavior. Existing
verification-based installers and probes intentionally inspect failed results.

The first execution-contract slice landed on 2026-08-09: strict failures now
raise, best-effort failures remain inspectable, and result-inspecting database,
release-fetch, and host-metric callers explicitly request `check=False`. The
helper also redacts common secret assignment and option values from command
output and exception text. Quoted or delimiter-bearing values can still leak
suffixes, and the helper has no timeout contract; the full caller
classification and complete secret-display audit remain open.

## Phase 2: Atomic persistent state

The first implementation slice (2026-08-09) created one shared atomic JSON
writer using a same-directory temporary file, flush and `fsync`, restrictive
mode, and `os.replace`, then migrated workspace caches, machine/setup state,
operation history, webhook/deploy configuration, release metadata, host/network
inventories, Cloudflare state, remote argument files, and Gogs credentials to
it.

Readers should distinguish:

- missing state, where defaults may be valid;
- invalid or corrupt state, which should name the file and remediation; and
- unsupported schema versions, which should fail without overwriting data.

State schemas should gain an explicit version when the next incompatible
change is required. Replace permissive corrupt-state fallbacks with an error
that names the file and remediation, while retaining defaults only for missing
state where they are valid.

## Phase 3: Staged service reconciliation

Manifest deployments now record application units, build and validate before
stopping app-scoped services, remove obsolete units only after activation, and
restore the previous release and units on failure. Unit preparation still
occurs during activation, but stop calls still use best-effort execution and
must fail closed before the release rename. The remaining work is to apply the
broader contract to non-manifest setup services and persist
interruption/recovery markers.

Replace cleanup-first setup with a staged reconciliation model:

1. Record the currently managed services and configuration artifacts.
2. Prepare new files and units without removing the active versions.
3. Validate generated configuration and executable prerequisites.
4. Stop only the services that must change.
5. Activate replacements and run health checks.
6. Remove obsolete managed services only after successful activation.
7. Restore the recorded state when activation fails.

A failed run should leave an operation marker explaining whether rollback
succeeded and which manual action remains. A later run must detect and resolve
that marker instead of silently starting another cleanup.

## Phase 4: Release activation and health gates

The manifest deployment path now stages releases, validates declared outputs,
gates activation on service startup and health, and restores the prior release
and unit files on failure. Immutable release history/current symlinks and
database migration policy remain open.

Deploy into immutable release directories and switch a stable `current` link
only after builds and preflight validation pass. Retain at least the previously
active release. Health checks must determine deployment success for components
that declare them.

Database migrations require a separate policy because switching application
files cannot always reverse a schema change. Record the migration boundary,
create and verify backups before migration, and clearly report when application
rollback also requires database restoration.

The remaining manifest work is durable operation history and explicit recovery
when a process or machine is interrupted during the short activation window.

## Phase 5: Managed SSH trust

Separate host-key enrollment from privileged operations. Enrollment should
display fingerprints for operator verification and persist approved keys in the
workspace. Subsequent setup, deploy, and transfer commands should require an
existing matching key. Host-key rotation needs an explicit command and audit
entry.

Interactive convenience commands may offer a clearly labelled trust-on-first-
use mode, but automated privileged paths should not enable it by default.

The remaining implementation slice must cover every SSH constructor, including
the Proxmox guest helper and CI/CD deploy-target enrollment. A successful
`ssh-keyscan` is discovery data, not operator approval; deployment must not be
enabled until the expected fingerprint is explicitly verified.

## Acceptance criteria

- A required command failure produces a non-zero top-level result and stops
  dependent steps.
- Injected failures before and after service stop preserve or restore the last
  healthy service.
- Interrupted state writes never replace valid JSON with a partial file.
- A declared health-check failure prevents deployment success.
- Operation history records apply, verification, rollback, and rollback result.
- Existing best-effort probes and optional installers retain intentional
  behavior through explicit APIs and tests.
- Hosted VM, unprivileged LXC, and direct Debian setup paths have regression
  coverage for the new phases.

## Recommended first delivery slice

The atomic persistence and initial execution-contract slices are complete. The
next delivery should finish the `remote_utils.run()` caller inventory and
transaction-framework decision, then use the shared writer for durable
operation markers and add fault-injection tests around setup/deployment
interruption.

## Non-goals

- Building a general distributed transaction system.
- Automatically reversing arbitrary repository-authored scripts.
- Pretending every database migration is reversible.
- Adding new supported operating systems during this work.
