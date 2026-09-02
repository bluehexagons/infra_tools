# Test suite audit (2026-09-02)

Status: complete for the current test-suite review. The suite has 170 tracked
test modules, 3,183 test methods, and 3,172 tests in the default runner. One
live Proxmox test is intentionally skipped unless explicitly enabled.

## Review method

Every tracked `tests/test_*.py` module, including `tests/service_tools/`, was
reviewed through unittest discovery, source/import inspection, AST scans for
assertions and duplicate bodies, and a check for stale test-to-production
references. The baseline command was:

```bash
python3 run_tests.py
```

The review looked for tests that had become disconnected from current code,
tests that could pass without proving behavior, exact duplicate test bodies,
and groups whose boundaries had become unclear as the repository grew.

## Findings and decisions

### No obsolete tests identified

All discovered test modules import successfully and pass in the default suite.
The legacy deployment tests remain useful: `deploy.deploy_steps` and
`DeploymentOrchestrator` are still active compatibility paths, and the tests
protect the supported static/Node behavior and the explicit Ruby refusal.

The only skipped default test is the destructive/live Proxmox lifecycle test.
It remains valuable as an opt-in integration check and is correctly isolated
behind the `live_proxmox` category.

Three exact duplicate-body pairs were found, but none is safe to remove:

| Pair | Why both remain |
| --- | --- |
| Modern `auto_restart` setting / legacy `no_restart` mapping | Current configuration and backwards-compatible configuration are separate contracts. |
| Routine privileged audit event / fail2ban unban event | Both verify the no-notification policy for different event sources. |
| Full Godot release update / bundle-only update | The updater receives different update results and both paths must notify. |

The 123 test methods without a direct `assert*` call are intentional
acceptance, syntax, idempotency, or side-effect tests. The progress fallback
test was the one weak exception: it claimed to verify fallback to `print` but
only checked that no exception was raised. It now captures and asserts the
actual output.

The audit also removed eleven unused imports from test modules. No test was
removed because no candidate met the project’s removal bar: deleting a test
must remove no distinct branch, compatibility rule, safety boundary, failure
path, or externally visible behavior.

## Grouping cleanup

The test files remain at their current paths to avoid a high-noise physical
move and fragile import/path churn. `run_tests.py` now provides pattern-driven
domain suites:

| Suite | Focus |
| --- | --- |
| `core` | Configuration, validation, state, logging, progress, and shared helpers |
| `agent` | Agent setup, credentials, workspaces, browser automation, and T3 Code |
| `network` | Network setup, DNS/mDNS, Cloudflare, SSH, and APT sources |
| `security` | Firewall, SSH hardening, Samba, shell safety, and access policy |
| `storage` | Storage, swap, sync/scrub, disk, and storage service tools |
| `proxmox` | Proxmox host, guest, VM, placement, and provisioning behavior |
| `web` | Gogs, Nginx, TLS, web panel, internal web, and Antistatic behavior |
| `desktop` | Desktop, XRDP, browser, Godot, firmware, and tool bundles |
| `deployment` | Setup, CI/CD, deployment, bootstrap, release, and packaging paths |
| `services` | Maintenance and service-tool entry points |

These suites intentionally overlap at cross-domain boundaries. The runner now
de-duplicates test cases when multiple suites or selectors overlap, so commands
such as the following are safe and predictable:

```bash
./run_tests.py --suite agent
./run_tests.py --suite storage --suite proxmox
./run_tests.py --suite deployment --suite web
```

The patterns are resolved from the repository at runner startup, which keeps a
new test with an established domain prefix from silently missing its domain
suite. The existing `smoke`, `proxmox`, `security`, and `integration` suites
remain available as targeted workflows; `all` and the default invocation still
use unittest discovery.

## Coverage review

The optional `coverage` package is not installed in this environment, so a
one-off standard-library `trace` run of `run_tests.py` was combined with an
AST statement-line map. This is an approximate prioritization signal, not a
branch-coverage gate: it measures the default suite only, counts a statement
as covered when its source line executed, and does not include the opt-in live
Proxmox test.

The run covered 29,723 of approximately 43,365 statement lines (68.5%) across
204 tracked non-test Python files. 189 files executed at least one statement;
15 did not. The largest gaps are concentrated in a small number of user-facing
and privileged workflows rather than in the validation code that has the most
test methods:

| Area | Approximate coverage | Evidence and meaningful next test |
| --- | ---: | --- |
| `lib/recall.py` | 17/132 (12.9%) | Interactive-shell tests patch the recall command; add focused tests for stored-config success, missing/invalid data, SSH timeout, reconstruction, and extra-feature rendering. |
| `lib/mount_utils.py` | 16/114 (14.0%) | Storage tests cover the `/mnt` predicate but not mountpoint ancestry, SMB probing, accessibility, callback failure, or multi-path results; add mocked-command tests with temporary directories. |
| `web/service_tools/webhook_manager.py` | 39/186 (21.0%) | Current coverage reaches the “default new repositories to main” behavior; exercise config absence, list/add/remove/test commands, duplicate handling, and script validation. |
| `web/service_tools/deploy_admin.py` | 40/176 (22.7%) | Existing tests focus on three validators; add temporary-directory tests for regular-file/size/owner checks, atomic replacement, symlink handling, rollback, and command failures. |
| `lib/remote_deploy.py` | 48/184 (26.1%) | Orchestration tests mostly patch the deployment helpers; cover rsync/SCP/SSH success, failure, timeout, cleanup, and safe-path branches directly with mocked subprocesses. |
| `lib/user_rename.py` and `common/service_tools/infra_web.py` | 36.2% and 44.4% | These are large, security-sensitive workflows. Add decision-table tests for rollback, idempotency, ownership, and failure transitions rather than shallow tests for every helper. |

The eight lazy sysadmin handlers (`sysadmin_fan`, `sysadmin_health`,
`sysadmin_keys`, `sysadmin_mount`, `sysadmin_reachable`, `sysadmin_ssh`,
`sysadmin_transfer`, and `sysadmin_upgrade`) did not execute at all in the
trace run. There are parser tests for the user-rename command, but no general
parser/dispatcher contract test for the sysadmin command family. This is the
highest-value addition: verify each `_sysadmin_cmd` dispatches the parsed
arguments correctly, then test handler success, failure, and credential
fallbacks with `subprocess.run`, `os.execvp`, and concurrency mocked.

Two other untraced modules deserve a code-ownership decision before new tests
are written. `lib/service_manager.py` and `lib/concurrent_sync_scrub.py` have
no repository consumers beyond their own definitions and no focused tests.
Confirm whether they are supported public paths; if not, remove the abandoned
implementations, and if so, wire them into the supported path and add tests.
The `deploy/steps.py` and `sync/steps.py` files are thin compatibility facades
and should instead get a cheap import/registration smoke test if they remain
part of the plugin contract. The untraced `scripts/` files are command-line
checks exercised by `make check`, so they are a lower-priority test gap.

Coverage should be improved as a risk-weighted branch matrix, not by chasing a
percentage through import-only tests. For command and system-mutating code,
the useful cases are validation refusal, dry-run/idempotent behavior, success,
external-command failure, timeout, and cleanup/rollback. All external commands
must stay mocked and filesystem cases should use temporary directories.

## Safe simplification opportunities

No additional test deletion is justified. A re-scan still finds only the three
exact duplicate-body pairs recorded above, and each pair protects a distinct
compatibility, event-source, or update-result contract. The roughly 123-method
“no direct `assert*`” signal is also not, by itself, test slop: most of those
tests are valid “must not raise” validator cases, syntax checks, idempotency
checks, or side-effect tests. Non-validator side-effect tests should continue
to assert a command, file, log, or return value explicitly.

The low-risk cleanup path is to reduce scaffolding while retaining test
identity and behavior coverage:

- Use `subTest` tables for closely related scalar validation cases in
  `test_validators.py` and `test_validation.py`, while keeping separate tests
  where the error message or security rule is materially different.
- Extract repeated mock setup/builders from broad service-tool tests when the
  setup is identical. This makes new failure-path tests cheaper without
  hiding which contract failed.
- Split large files only at existing behavior-class boundaries when a feature
  change provides a natural owner. Current candidates are
  `test_validation.py` (167 methods), `test_proxmox_manage.py` (107),
  `test_storage.py` (104), `test_agent_tools.py` (70),
  `test_antistatic_steps.py` (70), and `test_project_manifest.py` (66).
  The classes already provide useful grouping, so a mechanical move would add
  churn without improving coverage.

## Follow-up recommendations

- Keep large modules grouped by the behavior they protect. The most natural
  future physical splits are `test_validation.py`, `test_agent_tools.py`,
  `test_setup_common.py`, `test_provisioning_cache.py`, and
  `test_proxmox_manage.py`; defer them until a feature change gives each split
  a clear ownership boundary.
- Revisit older coverage when the corresponding implementation changes. The
  main watch list is the Proxmox helper cluster, `test_validators.py`,
  `test_disk_utils.py`, `test_progress_utils.py`, and
  `tests/service_tools/test_scrub_par2.py`. Their tests are still valid today,
  but their last focused updates predate later implementation changes.
- Keep compatibility and security tests even when their names contain
  “legacy”; age or terminology alone is not evidence of test slop.
- Treat the coverage priorities above as the backlog order: sysadmin dispatch,
  mount/recall utilities, privileged deployment helpers, then large workflow
  rollback matrices.

## Verification

- `python3 run_tests.py` — 3,172 passed, 1 skipped.
- `python3 run_tests.py test_progress_utils test_run_tests` — 48 passing.
- `make check` — compilation, documentation, packaging, artifact, and test checks passed.
- One-off `trace` plus AST review — approximately 68.5% of tracked production statement lines; 15 files untraced.
- `python3 -m py_compile run_tests.py tests/test_progress_utils.py tests/test_run_tests.py` — passing.
- `git diff --check` — passing after the final diff review.
