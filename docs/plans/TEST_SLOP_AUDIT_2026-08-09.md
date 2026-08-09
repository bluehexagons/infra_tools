# Test Slop Audit (2026-08-09)

Status: complete for this review slice. The repository currently has 102 test modules and about
1,900 test methods. This audit removes tests that add no distinct behavioral
evidence, while retaining boundary, failure, security, and integration
coverage.

## Review criteria

- Keep a test when deleting or breaking a distinct branch, boundary, safety
  rule, failure path, or externally visible output would make it fail.
- Cut tests that only repeat another input/output case, assert a trivial
  framework/parser default, or check setup mechanics without proving the
  resulting behavior.
- Treat command mocks as useful only when the exact command/order is itself a
  contract or a safety property.

## Initial candidates

| Candidate | Initial disposition | Reason |
| --- | --- | --- |
| `test_arg_parser_hosted.py`: default-`None` tests for hosted node, key, memory, and storage | cut | The parser declarations already establish ordinary optional-argument defaults; the surviving hosted-command and remote-parser tests prove the meaningful CLI boundary. |
| `test_progress.py:test_custom_width` | cut | It passed `width=40` but only checked `50%`, duplicating `test_half_progress`; it never proved the width behavior. |
| `test_proxmox_summary.py` formatting presence tests | undecided | Some are single-substring smoke checks, but the summary is user-facing CLI output. |
| `test_ruby_setup.py` existing-install and step-wiring tests | undecided | They are mock-heavy, but idempotency and system-profile wiring may be important contracts. |

## Decisions

The parser-default candidates were checked against `lib/arg_parser.py`,
`SetupConfig` defaults in `tests/test_config.py`, and its hosted/remote
callers. The remaining positive flag tests and full hosted command test cover
values that affect setup behavior; the default-only tests added no distinct
evidence. Four tests were removed.

The progress candidate was checked against `lib/progress.py`: because its only
assertion was the percentage, it could not detect a broken `width` argument.
It was removed rather than replaced by a misleading test. One test was
removed.

The Proxmox summary formatting tests remain. Although each is small, they cover
user-facing output fields and conditional swap output; together they protect
the CLI summary contract rather than merely exercising a parser declaration.

The Ruby existing-install and step-wiring tests remain. The first protects
idempotency and the second protects profile selection, both of which can fail
without changing the mocked command shape.

## Verification

- Run the full unittest discovery command after edits.
- Run `git diff --check` and inspect the final diff.
- Targeted parser/progress/config check: 115 tests, passing.
- Full discovery: 1,895 tests ran, 1 skipped, all passing.
- Commit and push the audit changes only after the working tree and test suite
  support the decisions above.
