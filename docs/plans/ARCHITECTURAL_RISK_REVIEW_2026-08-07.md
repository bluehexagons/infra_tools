# Architectural Risk Review (2026-08-07)

Status: active roadmap input. This is a focused design/operability risk
document; implementation priorities are tracked in [the project roadmap](ROADMAP.md).

## Scope

This pass reviewed operational and architectural behavior in the setup/deploy and CI/CD flows with no code execution beyond read-only inspection.

Primary evidence sources were:

- `lib/remote_utils.py`
- `lib/plugin_registry.py`
- `lib/machine_state.py`
- `lib/validation.py`
- `lib/ssh_utils.py`
- `lib/remote_deploy.py`
- `remote_setup.py`
- `lib/deployment.py`
- `web/service_tools/cicd_executor.py`
- `lib/cache.py`
- `web/service_tools/webhook_manager.py`

## Findings (validated)

Each finding lists: severity, evidence, validation outcome, and direct follow-up impact.

### ARCH-01: Ambiguous execution helper (`remote_utils.run`) (resolved)

**Severity: High**

- **Evidence**
  - The helper has hundreds of callers, including required setup commands and
    probes that intentionally inspect a non-zero result.
  - Before the execution-contract slice, `check=True` only printed a warning;
    required failures therefore looked like successful setup steps.
  - `install_with_verify()` and other probes intentionally use
    `check=False` and inspect the returned result.
- **Validation**
  - Confirmed by tests that `check=True` now raises the project-specific
    `CommandExecutionError` with the display command, exit code, and bounded
    stderr, while `check=False` returns the failed `CompletedProcess`.
  - The first caller audit migrated result-inspecting database, release-fetch,
    and host-metric paths to explicit `check=False`; the remaining inventory is
    still tracked in the transactional execution plan.
- **Impact**
  - The helper now stops required command chains by default, while preserving
    explicit best-effort behavior for probes and optional operations.
  - Remaining partial-apply and recovery risks are tracked under ARCH-03,
    ARCH-05, and ARCH-08 rather than hidden by a warning-only helper.

### ARCH-02: Plugin discovery is eager and import-coupled to startup

**Severity: High**

- **Evidence**
  - `lib/plugin_registry.py:74-90` imports every module in `plugins/` during registry discovery.
  - `lib/plugin_registry.py:213-218` memoizes the registry from discovery at module call site.
  - `lib/machine_state.py:13` imports `get_system_type_names`, and `lib/validation.py:13` imports `resolve_validator`; both depend on plugin discovery.
- **Validation**
  - Confirmed by line-by-line inspection that a malformed plugin import can raise before runtime operations are complete.
- **Impact**
  - A bad plugin definition can abort unrelated startup paths before command logic can present a controlled, recoverable failure.

### ARCH-03: SSH trust configuration is inconsistently enforced

**Severity: High**

- **Evidence**
  - `lib/ssh_utils.py` now sets `StrictHostKeyChecking=yes` and points shared
    builders at the workspace `known_hosts` file.
  - `lib/proxmox_guest.py::_ssh_opts()` now uses the workspace file; this
    bypass was resolved on 2026-08-21.
  - `web/build_server_steps.py::configure_deploy_known_hosts()` appends
    `ssh-keyscan` output without authenticating the fingerprint first.
- **Validation**
  - Confirmed by comparing the shared builders, the separate Proxmox constructor,
    and the CI/CD deployment-target bootstrap path.
- **Impact**
- Shared and Proxmox paths are strict. Unauthenticated CI/CD enrollment still
  leaves deployment paths exposed to incorrect host-key trust.

### ARCH-04: CI/CD executes repo-authored scripts with broad execution scope

**Severity: High**

- **Evidence**
  - Local deploy/test/build scripts are executed with `/bin/bash -lc` in `run_script()` (`web/service_tools/cicd_executor.py:263-270`) using repository-provided paths.
  - Remote deploy scripts are read then piped as stdin to SSH command (`_build_ssh_stdin_script_cmd` + `subprocess.run(..., input=script_content)`) at lines 506-515.
- **Validation**
  - Confirmed that repository scripts are not just parsed but executed directly in CI execution context.
- **Impact**
  - Remote command execution boundary is effectively “script file is trusted,” which is acceptable only with strict review/validation controls. Current code provides low friction.

### ARCH-05: Remote setup "cleanup first" has no rollback/failover protection (resolved)

**Severity: Medium-High**

- **Evidence**
  - The global pre-setup service cleanup was removed on 2026-08-19.
  - Manifest deployments reconcile only the application's units after a staged
    build and artifact validation succeeds.
- **Validation**
  - Regression tests verify build and artifact failures occur before app
    services are stopped, and failed activation restores the previous release.
- **Impact**
  - Setup no longer creates an outage for every managed application before
    unrelated work. Broader non-manifest setup rollback remains tracked in the
    transactional execution plan.

### ARCH-06: State/cache file writes were best-effort and non-atomic (resolved)

**Severity: Medium**

- **Evidence**
  - The shared `lib.atomic_io.write_json_atomic()` now protects all project
    JSON state/configuration writes, including machine/setup state,
    caches/history, webhook configuration and jobs, deployment/release
    metadata, host/network inventories, Cloudflare state, deploy-target config,
    remote argument files, security/maintenance cursors, and Gogs admin
    credentials.
  - Readers such as `lib.machine_state.py:165-170` and `lib.cache.py:129-140`
    still swallow decode/I/O errors and fall back to defaults or omission.
- **Validation**
  - Confirmed by direct line inspection of write and fallback paths.
- **Impact**
  - The partial-write risk is closed for JSON state/configuration, but corrupted
    state can still be hidden by permissive readers and lacks schema-versioned
    remediation.

### ARCH-07: Manifest/build env assembly did not validate variable names (resolved)

**Severity: Medium**

- **Evidence**
  - `lib/deployment.py:802` composes `env_prefix` with unchecked `key` and only quoted `value` in shell command string.
  - `lib/deployment.py:806` concatenates that prefix into a `/bin/bash -lc` command path.
- **Validation**
  - Confirmed in manifest deployment path that this path exists and keys are accepted unvalidated from manifest data.
- **Impact**
  - Potential injection through attacker-controlled key names if manifest source is not fully trusted.

### ARCH-08: Input validation is fragmented across modules

**Severity: Medium**

- **Evidence**
  - `lib/cache.py`, `lib/machine_state.py`, and config loaders tend to warn + continue on decode/validation errors rather than fail hard.
  - `lib/remote_setup.py` writes state/config before executing steps; many downstream modules assume state exists.
- **Validation**
  - Confirmed through comparison of validation and handling patterns in inspected files.
- **Impact**
  - Debugging setup failures is harder; silent fallback can mask real data-corruption or malformed-input scenarios.

## Validation log

Validation was performed by static evidence checks (no behavior-altering actions):

- Line-numbered inspection (`nl -ba`) on all files above to anchor exact findings.
- Pattern scans for high-risk command behaviors (`rg -n`) before file-by-file inspection.
- Cross-check of comments in source (self-documenting caveats in `remote_setup.py` and `lib/remote_deploy.py`).

## Suggested next actions (ordered)

1. Make execution helper semantics explicit (`run` should either raise or return a structured failure contract; avoid ambiguous `check=True` behavior).
2. Add import-time fault isolation for plugin/validator discovery (cache and quarantine malformed plugin modules).
3. Route every SSH constructor through managed known-hosts and replace
   unauthenticated `ssh-keyscan` bootstrapping with explicit fingerprint
   enrollment.
4. Make setup teardown transaction-like (snapshot, apply, rollback marker) so cleanup failures are reversible.
5. Tighten corrupted-state behavior with schema versions and explicit
   remediation; audit remaining non-JSON configuration writes for the same
   atomic and permission guarantees.
6. Keep repository-script execution as an explicit trust boundary while the
   direct and webhook deployment engines converge.

## Resolution updates

- **2026-08-08 — ARCH-07 resolved:** manifest environment variable names are
  now validated as shell identifiers before deployment command assembly. Keep
  this validation at the manifest boundary when the build executor is refactored.
- **2026-08-09 — historical revalidation:** at that point setup still removed
  managed services before running steps, manifest deploy replaced the active
  tree before building, and health failures only warned. Those deployment
  findings were resolved on 2026-08-19. Shared SSH builders use strict workspace
  enrollment, but the Proxmox and CI/CD gaps described in ARCH-03 remained at
  that point; plugin discovery still imports every built-in plugin eagerly, and
  corrupt-state handling remains permissive.
- **2026-08-09 — ARCH-06 resolved:** introduced the shared writer and migrated
  all JSON state/configuration paths, including secret-bearing files with mode
  `0600`. Tests cover complete writes, replacement failure preservation, and
  permissions. Corrupt-state remediation remains tracked under ARCH-08.
- **2026-08-09 — ARCH-01 resolved:** `remote_utils.run(check=True)` now raises
  `CommandExecutionError` on non-zero exit, with bounded diagnostics, while
  `check=False` remains an explicit result-returning contract. Tests cover both
  paths, and common secret assignment/option values are redacted from command
  output and exception text. Caller inventory and a complete secret-display
  audit remain follow-up work.
- **2026-08-19 — ARCH-05 resolved:** removed global service teardown from
  remote setup. Manifest deployments now build and validate before stopping
  app-scoped units, then restore the prior release and units after activation
  or health failure. Durable interruption markers remain open work.
- **2026-08-21 — ARCH-03 partially resolved:** Proxmox node connections now use
  strict workspace host-key enrollment, including multiplexed control-socket
  paths. CI/CD deploy-target enrollment remains unauthenticated.
- ARCH-01, ARCH-03, and ARCH-08 are sequenced in
  [Transactional execution and reconciliation](TRANSACTIONAL_EXECUTION.md).
  ARCH-02 remains a P3 startup-isolation task in [the roadmap](ROADMAP.md), and
  ARCH-04 is a trust-boundary requirement for
  [CI/CD manifest reuse](CICD_MANIFEST_REUSE.md).
