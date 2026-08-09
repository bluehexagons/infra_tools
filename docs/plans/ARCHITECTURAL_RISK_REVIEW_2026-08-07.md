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

### ARCH-01: Non-failing execution helper (`remote_utils.run`)

**Severity: High**

- **Evidence**
  - `lib/remote_utils.py:62-66` calls `subprocess.run(...)` and does **not** raise on non-zero status when `check=True`; it only prints a warning.
  - Same pattern is then widely used by callers that expect the helper to enforce failures.
  - `install_with_verify()` intentionally invokes `run(install_cmd, check=False)` at `lib/remote_utils.py:131`, which is consistent with a soft-fail helper model, but then this behavior is also applied in other paths where callers rely on return code.
- **Validation**
  - Confirmed by line-level inspection that `check` only toggles warning behavior and never raises.
- **Impact**
  - Command failures can continue through orchestrations and produce partially-applied state.  
  - Inconsistent local recovery logic makes operational behavior hard to reason about.

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

### ARCH-03: SSH trust configuration still permits first-connect risk

**Severity: High**

- **Evidence**
  - `lib/ssh_utils.py:50`, `86`, `113` set `StrictHostKeyChecking=accept-new`.
  - `lib/remote_deploy.py` carries same policy plus explicit warning in `push_artifact` lines 103-107.
- **Validation**
  - Confirmed in all three SSH helper constructors (`build_ssh_command`, `build_scp_command`, `build_rsync_ssh_transport`) and caller path in deploy module.
- **Impact**
  - First-time host-key acceptance on privileged deploy paths remains MITM-sensitive.

### ARCH-04: CI/CD executes repo-authored scripts with broad execution scope

**Severity: High**

- **Evidence**
  - Local deploy/test/build scripts are executed with `/bin/bash -lc` in `run_script()` (`web/service_tools/cicd_executor.py:263-270`) using repository-provided paths.
  - Remote deploy scripts are read then piped as stdin to SSH command (`_build_ssh_stdin_script_cmd` + `subprocess.run(..., input=script_content)`) at lines 506-515.
- **Validation**
  - Confirmed that repository scripts are not just parsed but executed directly in CI execution context.
- **Impact**
  - Remote command execution boundary is effectively “script file is trusted,” which is acceptable only with strict review/validation controls. Current code provides low friction.

### ARCH-05: Remote setup "cleanup first" has no rollback/failover protection

**Severity: Medium-High**

- **Evidence**
  - `remote_setup.py:219-227` intentionally removes existing infra_tools services before iterating install steps.
  - Immediate follow-on comments acknowledge that services remain removed if subsequent steps fail (`remote_setup.py:221-223`).
- **Validation**
  - Confirmed by inline comments and call order before `get_steps_for_system_type(config)`.
- **Impact**
  - Partial outages are possible on failed setup runs; cleanup becomes user-facing operational debt until rerun success.

### ARCH-06: State/cache file writes are best-effort and non-atomic

**Severity: Medium**

- **Evidence**
  - `lib/machine_state.py:128-129`, `lib/cache.py:76-79`, `lib/cache.py:112-114`, and `web/service_tools/webhook_manager.py:46-48` write JSON directly via `open(..., "w")` without temp-file+rename.
  - `lib/machine_state.py:165-170` and `lib/cache.py:168-170` swallow JSON/OSError and fall back to defaults/default config.
- **Validation**
  - Confirmed by direct line inspection of write and fallback paths.
- **Impact**
  - Crash/interruption during write can leave corrupted state; recovery by fallback silently hides corruption and increases debugging latency.

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
3. Replace `accept-new` in production deploy paths with managed known-host bootstrapping and `yes/no` policy enforcement.
4. Make setup teardown transaction-like (snapshot, apply, rollback marker) so cleanup failures are reversible.
5. Convert all persistent JSON writes to atomic temp-file write + `os.replace`, and tighten behavior on corrupted state to surface explicit remediation steps.
6. Keep repository-script execution as an explicit trust boundary while the
   direct and webhook deployment engines converge.

## Resolution updates

- **2026-08-08 — ARCH-07 resolved:** manifest environment variable names are
  now validated as shell identifiers before deployment command assembly. Keep
  this validation at the manifest boundary when the build executor is refactored.
- **2026-08-09 — open findings reverified:** `run(check=True)` still returns a
  failed result, setup still removes managed services before running steps,
  manifest deploy still removes the active tree before building, manifest
  health failures still warn without failing, the shared SSH builders still
  use `accept-new`, plugin discovery still imports every built-in plugin
  eagerly, and the named state/cache files still use direct JSON writes.
- ARCH-01, ARCH-03, ARCH-05, ARCH-06, and ARCH-08 are sequenced in
  [Transactional execution and reconciliation](TRANSACTIONAL_EXECUTION.md).
  ARCH-02 remains a P3 startup-isolation task in [the roadmap](ROADMAP.md), and
  ARCH-04 is a trust-boundary requirement for
  [CI/CD manifest reuse](CICD_MANIFEST_REUSE.md).
