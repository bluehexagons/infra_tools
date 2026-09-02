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

## Verification

- `python3 run_tests.py` — 3,172 passed, 1 skipped.
- `python3 run_tests.py test_progress_utils test_run_tests` — 48 passing.
- `make check` — compilation, documentation, packaging, artifact, and test checks passed.
- `python3 -m py_compile run_tests.py tests/test_progress_utils.py tests/test_run_tests.py` — passing.
- `git diff --check` — passing after the final diff review.
