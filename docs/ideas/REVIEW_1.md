# REVIEW_1 Workspace, Credential, and Execution Hardening

This document describes the architecture and security changes implemented by the REVIEW_1 pull request.

## Scope

REVIEW_1 establishes a new foundation for how `infra_tools` stores local state, manages reusable credentials, validates user input, resolves system types, and executes remote setup work. The changes are intended to replace the older cache- and wrapper-script-based model with a unified CLI and a workspace-scoped runtime model.

## Unified CLI Surface

`infra_tools.py` is now the primary user-facing entry point for setup, patching, saved-configuration management, recall, reconstruction, completions, local Python tooling, orchestration-host bootstrap, and credential management.

The older per-system setup wrappers and standalone helper entry points have been removed from the normal user workflow. Persisted workspace metadata now records the unified entry point instead of obsolete `setup_<system_type>.py` wrapper names.

## Workspace-Based State

Workspace state now lives under `~/.config/infra_tools` by default, or under the path selected with `--workspace`.

The workspace contains:

- `setups/` for saved setup definitions
- `credentials.json` for shared username/password mappings
- `known_hosts` for SSH host trust managed by `infra_tools`
- `history/` for sanitized records of completed setup and patch runs

Completed runs write sanitized JSON history entries into `history/`. Saved setup state and history contain the requested configuration and execution metadata, but they do not persist resolved passwords.

## Credential Handling

Workspace credentials are managed through `infra_tools.py credentials` and through the convenience `--credential USERNAME PASSWORD` path on setup and patch commands.

The credential store:

- uses a versioned JSON structure at the workspace root
- enforces `0600` permissions
- stores one reusable password per username for this revision
- supports listing, setting, and removing credentials

Runtime credential resolution now pulls saved credentials into Samba shares, SMB mounts, and other password-based operations without requiring repeated inline `username:password` values in user-facing commands.

## Remote Execution and Secret Handling

Remote setup execution now stages project artifacts locally, streams them to the target host over SSH stdin as a tar archive, and executes `remote_setup.py` on the remote side.

Runtime arguments are written to a temporary JSON args file with `0600` permissions before transfer, and `remote_setup.py` consumes and deletes that file on the remote host. This keeps resolved passwords out of the local SSH process command line while still allowing the remote run to reconstruct the requested setup configuration.

Remote artifact bundling includes the top-level `plugins/` package along with the main code directories so plugin-based system-type discovery works on live remote runs.

## Plugin-Based System Types

System-type discovery is now driven by a built-in plugin registry.

The registry provides:

- automatic discovery of built-in plugins from `plugins/`
- explicit plugin roles (`base`, `capability`, `composition`)
- deterministic dependency resolution
- plugin-owned system-type registration
- plugin-owned custom-step registration
- plugin-owned validator registration
- fail-fast duplicate and conflict detection

Current built-in plugins cover shared/common functionality, desktop features, security hardening, SMB support, sync/storage behavior, web/deployment behavior, workstation compositions, server compositions, and Proxmox-specific compositions.

This plugin contract is sufficient for the current system types and is the supported model for REVIEW_1.

## Validation and Safer Defaults

CLI entry points now validate external inputs before setup or patch execution continues. This includes:

- workspace paths
- usernames and hosts
- notification targets
- timezones
- SSL registration email addresses
- custom APT package names
- deploy specs and deploy targets
- Samba shares and SMB mounts
- sync and scrub storage specs
- hosted/Proxmox container options

Secure defaults introduced in this revision include:

- no generated default login passwords during setup
- workspace-managed SSH `known_hosts`
- workstation flows that do not enable RDP by default
- sanitized persisted state and execution history

## Logging and Observability

Service-oriented helpers now use shared structured logging utilities for stable `key=value` event context. The REVIEW_1 work applies this to the major service tools involved in CI/CD execution, storage operations, automatic maintenance, xRDP session cleanup, and webhook handling.

Interactive CLI setup and patch commands remain human-readable, while long-running helpers and services emit structured operational logs that avoid credential disclosure.

## Testing and Regression Coverage

The REVIEW_1 changes are covered by focused tests for:

- workspace path handling and workspace-aware CLI behavior
- credential storage and runtime credential resolution
- plugin registry behavior and plugin-owned step/validator registration
- remote setup arg-file handling
- cache/history persistence behavior
- SSH command building and command-safety behavior

The repository also includes a regression test that fails if Python source reintroduces `shell=True` subprocess usage.

At the time this document was last updated, `python3 -m unittest discover -s tests` passed with 977 tests.

## Live-System Readiness

This branch is intended to be suitable for controlled live-system testing.

In particular:

- persisted local state is isolated under the selected workspace
- reusable credentials are centralized and permission-restricted
- remote setup avoids exposing resolved passwords in local process arguments
- plugin discovery works in both local and remote execution contexts
- saved setup/history metadata reflects the unified CLI surface
- the current regression suite covers the highest-risk command-construction, validation, credential, and workspace behaviors introduced by REVIEW_1

## Deferred Follow-Up Work

The following items remain reasonable future improvements, but they are not blockers for this REVIEW_1 branch:

- broader type-checking and pre-commit automation
- expanded integration testing beyond the current targeted regression suite
- additional metrics and diagnostics for long-running service workflows
