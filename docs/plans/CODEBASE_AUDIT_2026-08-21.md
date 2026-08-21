# Codebase Audit and Maintenance Review (2026-08-21)

Status: active roadmap input. This review records verified maintenance and
operational gaps found across the repository; implementation sequencing remains
owned by [the project roadmap](ROADMAP.md).

## Scope and verification

This pass covered setup orchestration, persistent state, SSH and host-key
handling, network transitions, Proxmox lifecycle commands, CI/CD webhooks and
deployment, agent updates, transaction/logging helpers, packaging metadata, CI,
and focused tests and documentation.

Verification included:

- `make check`: compilation, CLI documentation and package metadata checks, and
  the full unittest suite passed (2,402 tests, one skipped in the audit run).
- A setuptools wheel build from `pyproject.toml`, followed by extraction into a
  clean directory and an import smoke test.
- Line-level source inspection and repository-wide searches for command failure
  contracts, destructive operations, rollback markers, host-key options, and
  transaction-framework callers.
- Focused reproductions of command redaction with quoted and delimiter-bearing
  values, plus review of source/config staging and release activation failure
  paths.
- Final worktree and whitespace checks after documentation changes.

## Findings

### AUD-01: The declared wheel is not self-contained (resolved)

**Severity: High — release and installation maintenance**

`pyproject.toml` declares `py-modules = ["infra_tools", "remote_setup"]`, while
the entry points import `lib`, `common`, `plugins`, `web`, `security`, and other
source packages. The built wheel contained only the two top-level modules and
metadata. Importing `infra_tools` from the extracted wheel failed with
`ModuleNotFoundError: No module named 'lib'`.

The release workflow runs `make check` and publishes a GitHub release, but it
does not build, install, or smoke-test a wheel. The source-worktree installer
currently masks this packaging defect.

**Resolution (2026-08-21):** package discovery now includes every runtime
package and required desktop/web template, while retaining the two top-level
modules. A clean virtual-environment check inspects the wheel, imports its
runtime packages outside the source tree, and runs both installed launchers.
Tagged-release CI builds, verifies, and attaches that wheel before publication.

### AUD-02: CI/CD deployment targets are enrolled from unauthenticated scans

**Severity: High — host-key trust**

`web/build_server_steps.py` runs `ssh-keyscan` for every deployment target and
appends the result to the service account's `known_hosts` file. The command uses
`check=False`; any successful network response becomes trusted material before a
first production deployment. `docs/CICD.md` asks an operator to verify the
fingerprints afterward, but the trust decision has already been staged.

**Follow-up:** require operator-supplied fingerprints or an explicit enrollment
step, validate the resulting key before enabling deployment, and record key
rotation as an auditable action.

### AUD-03: Proxmox node SSH bypasses the workspace known-hosts policy (resolved)

**Severity: High — inconsistent SSH enforcement**

`lib/ssh_utils.py` routes shared SSH/SCP/rsync builders through the workspace
`known_hosts` file with `StrictHostKeyChecking=yes`. The separate
`lib/proxmox_guest.py::_ssh_opts()` helper sets strict checking but does not set
`UserKnownHostsFile`, so Proxmox node connections consult OpenSSH's normal host
files instead of the enrollment store described by the SSH documentation.

**Resolution (2026-08-21):** the Proxmox SSH option builder now uses the shared
workspace `known_hosts` path. Guest provisioning, node probes, and multiplexed
control-socket commands all consume that option list, and focused tests assert
the workspace path with and without a dedicated identity key.

### AUD-04: Target setup state is saved before setup steps execute

**Severity: Medium-High — recovery and reconciliation**

`remote_setup.py` writes machine state and the recalled setup configuration
immediately before entering the step loop. If a later step fails, the target
retains the new remembered configuration without a durable in-progress marker or
success record. The controller's setup history does not make that target-local
state safe to replay after interruption.

**Follow-up:** write a versioned operation marker before mutation, finalize
remembered state only after successful verification, and make interrupted or
failed runs visible to the next invocation.

### AUD-05: Required setup mutations still have weak failure contracts

**Severity: Medium-High — partial apply**

Several required paths use best-effort subprocess calls without checking the
result at the owning step. Examples include package/service setup in
`web/web_steps.py`, firewall initialization in `security/security_steps.py`, and
CI/CD prerequisite installation in `web/cicd_steps.py`. This is distinct from
intentional probes and cleanup calls, which should remain explicit
`check=False` operations.

**Follow-up:** finish the caller inventory from
[Transactional execution](TRANSACTIONAL_EXECUTION.md), classify each command as
required, optional, probe, or cleanup, and add step-level tests that prove a
required package, firewall rule, service, or configuration failure reaches the
top-level result.

### AUD-06: Corrupt state is hidden by permissive readers

**Severity: Medium — operability and drift**

`lib/release_management.py`, `lib/cache.py`, and `lib/machine_state.py` convert
JSON decode/I/O/type failures into `{}`, omission, or automatic detection. The
atomic writer prevents partial replacement, but a deliberately or accidentally
corrupted complete file can still make the system behave as though saved state
never existed.

**Follow-up:** distinguish missing state from invalid state, add schema versions
where compatibility matters, name the affected file in the error, and provide a
documented backup/quarantine/remediation path.

### AUD-07: Signed webhook deliveries can be replayed

**Severity: Medium — deployment reliability and integrity**

The receiver verifies the HMAC and commit fields, but never reads or records
`X-GitHub-Delivery`. Every valid repeat of a delivery creates a new nonce-bearing
job file, so the executor can rebuild and redeploy the same commit more than
once. Consuming each queue file after one attempt does not provide delivery
idempotency.

**Follow-up:** persist bounded delivery IDs (with repository/commit context and
expiry), reject or coalesce repeats, and add a replay regression test. Keep the
existing one-attempt queue consumption behavior as a separate malformed-job
safety measure.

### AUD-08: Destructive snapshot deletion lacks the CLI confirmation contract

**Severity: Medium — operator safety**

`infra-tools proxmox delsnapshot` validates the snapshot name and executes the
remote deletion, but exposes only `--dry-run`; unlike guest destruction and
orphan-volume deletion it has no `--yes` switch or interactive confirmation.

**Follow-up:** apply one documented confirmation contract to irreversible
Proxmox commands and test both interactive refusal and explicit non-interactive
approval.

### AUD-09: Agent update trust is recorded, not verified

The Codex agent updater downloads and executes the current script at
`https://chatgpt.com/codex/install.sh`, records its SHA-256, and validates size
and post-update behavior. The digest is an audit record, not an authenticity
check; no pinned digest, signature, or release-channel policy is enforced.

**Follow-up:** define the supported update trust model—vendor signature, pinned
digest manifest, or an explicitly documented rolling-channel exception—and make
the policy visible in the update result and maintenance documentation.

### AUD-10: Command redaction leaks quoted secret suffixes (resolved)

**Severity: High — diagnostic secret exposure**

`lib/remote_utils.py::_redact_command()` redacts only up to whitespace,
semicolons, and pipe characters. It does not parse shell quoting. For example,
`--password 'secret phrase'` is rendered as `--password <redacted> phrase'`,
and a quoted value containing `;` leaves the suffix visible. This affects both
the normal command log and `CommandExecutionError` diagnostics. It is relevant
to generated passwords because the supported password alphabet includes shell
metacharacters.

**Resolution (2026-08-21):** diagnostic redaction now consumes complete
shell-style values without evaluating them. It handles single and double
quotes, escaped whitespace, concatenated word segments, shell delimiters inside
quotes, and unterminated quoted input. Regression tests cover both command and
stderr diagnostics. A future argv-native command API can further reduce string
reconstruction, but the demonstrated suffix disclosure is closed.

### AUD-11: The shared command runner has no timeout contract (resolved)

**Severity: Medium — hung setup/deployment operations**

`lib/remote_utils.run()` passes no `timeout` to `subprocess.run()`. It is used
by hundreds of setup, deployment, package, service, and network callers, so a
stalled package manager, service action, child process, or shell command can
hold the operation indefinitely. A few specialized paths add their own shell
timeouts, but the shared helper does not expose or enforce a caller-visible
timeout policy.

**Resolution (2026-08-21):** `run()` now applies a one-hour default bound and
accepts an explicit positive timeout or `None` for a deliberately unbounded
operation. Timeouts raise `CommandTimeoutError` regardless of `check`, because
there is no completed result for best-effort callers to inspect. Shell commands
start in a separate session; timeout cleanup sends TERM and then KILL to the
whole process group. Tests cover the default, invalid values, secret-safe
diagnostics, best-effort propagation, and process-group cleanup. Commands known
to require more than an hour must opt into a larger bound at the call site.

### AUD-12: Active agent config staging follows source symlinks (resolved)

**Severity: Medium-High — local file disclosure boundary**

`lib/setup_common.py::_copy_existing_path()` follows a symlink for a file via
`shutil.copy2()` and preserves symlinks while copying directories. The helper
is used for selected active agent configuration such as Codex, Claude, OpenCode,
and GitHub CLI config. The credential-specific path rejects symlink sources,
but the general config path does not, so a user-selected config copy can stage
content outside the expected home/config tree into the remote payload.

**Resolution (2026-08-21):** agent config staging now fails closed when the
selected source file or directory is a symlink, and checks every directory
entry before copying without following links. Non-regular top-level sources are
also rejected. Temporary-directory tests cover symlinked config files,
symlinked config roots, and directory symlinks nested below a real config root.
Credential-specific regular-file validation remains in place.

### AUD-13: Manifest activation proceeds after service-stop failure (resolved)

**Severity: Medium-High — release/process split-brain**

`lib/deployment.py::deploy_manifest()` stops app units with `check=False` and
does not inspect the result before renaming the active release directory. If a
unit cannot be stopped, the old process can remain alive while the service
definition and active tree are changed. The later rollback path also treats
stop/restart failures as best effort, which can leave the operator with a
partially restored process set even when the release tree is restored.

**Resolution (2026-08-21):** manifest deployment now stops existing app units
before the release rename and verifies each unit became inactive. A failed stop
aborts activation; units already stopped earlier in that phase are restarted
and verified against the unchanged release. Post-activation rollback continues
restoring the release tree even when a unit stop fails, verifies every restored
unit restart, and reports incomplete service recovery instead of claiming a
clean rollback. Fault-injection tests cover stop failure before activation,
rollback stop failure, and inactive/active verification failures.

## Positive controls verified

- Shared SSH builders already require strict host-key checking; the remaining
  issue is policy bypass/inconsistent enrollment, not a blanket `accept-new`
  default.
- The live network handoff persists a transition identity and rollback snapshot,
  verifies SSH at the requested address before commit, and aborts on failed
  verification. Its cleanup commands are deliberately best-effort and should
  not be generalized to required setup mutations.
- Proxmox guest destruction and orphan-volume cleanup require explicit
  confirmation, and the network transition has focused identity/rollback tests.
- The callback-based transaction framework was retired after this audit.
  Sync/scrub operations now use explicit fail-fast control flow, while the
  operation logger remains diagnostic evidence. The main setup/deployment paths
  still need a small durable operation marker rather than another callback
  abstraction.

## Recommended order

1. Fix packaging metadata and add artifact smoke tests to release CI.
2. Close host-key enrollment inconsistencies for CI/CD and Proxmox.
3. Add durable setup operation markers and finish required-command caller
   classification.
4. Fix command redaction and define bounded command execution, then make
   config staging reject source symlinks and deployment stop failures fail fast.
5. Make corrupt-state failures actionable and add webhook delivery idempotency.
6. Standardize destructive CLI confirmation and define the agent updater trust
   policy.
