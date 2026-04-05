# infra_tools Architecture and Security Review Plan

## Overview
This document outlines a plan for major architectural and security improvements to the infra_tools codebase. As this is a major revision, backwards compatibility is not required and existing cached setup state will be intentionally replaced instead of migrated.

## Primary Focus Areas
1. **Security Hardening** - Eliminate injection vulnerabilities and improve secure handling of sensitive data
2. **Architectural Improvements** - Refactor for better maintainability, testability, and extensibility
3. **Validation Enhancement** - Strengthen input validation throughout the codebase
4. **Error Handling & Logging** - Implement consistent, secure error handling and logging

## Detailed Implementation Plan

### Phase 1: Security Foundation
#### 1.1 Remove SSH/Login Password Command-Line Exposure
- Eliminate SSH/login password acceptance via command-line arguments
- Implement SSH key-only authentication for remote operations wherever possible
- Add interactive password prompts only for SSH/login flows that cannot use keys
- Update all related configuration and argument parsing
- Keep non-login credentials supported, but stop routing them through ad hoc flags and inline command-line values where avoidable
- Stop generating default random login passwords during setup; allow passwordless user creation/setup when a password is not explicitly required
- If no password is provided for setup, create the user account without setting a local password and rely on SSH key authentication
- Do not change or remove passwords for existing accounts unless a password is explicitly provided

#### 1.2 Credential Management Strategy
- Add a unified credentials store within the workspace configuration directory (JSON state file for this pass)
- Add `infra_tools.py credentials [command] [args]` for credential management with built-in help output
- Support `credentials set USERNAME PASSWORD`, `credentials list`, and `credentials remove USERNAME`
- Allow setup/patch flows to accept `--credential USERNAME PASSWORD` as a convenience path that writes to the shared credential store
- Treat the workspace credential file as the single source of truth for saved credentials
- Use a simple global credential mapping for this pass: one username maps to one password regardless of host or operation type
- Use per-credential objects for extensibility, e.g. `{ "version": 1, "credentials": { "alice": { "password": "secret" } } }`
- Require `credentials.json` to use `0600` permissions; fix permissions automatically when possible and warn/fail when secure handling is not possible
- Replacing an existing stored credential should happen silently to keep CLI automation simple
- Allow Samba shares, SMB mounts, deployments, and other password-based features to resolve credentials from the shared store instead of requiring repeated `username:password` inputs
- Credentials specific to a deployment should be transferred to the remote system through a more secure setup channel instead of command-line flags
- Keep the stored credential model intentionally simple even if consumers use it for SSH/login, Samba/share, SMB mount, deployment, or other service-specific operations
- Prefer the explicit `credentials` subcommand for management operations; keep `--credential` as a convenience write path only
- Support password-free RDP via SSH tunnel (xRDP over SSH):
  - Configure xRDP to not require password (password=ask or empty with PAM)
  - Client connects via SSH tunnel: `ssh -L 3389:localhost:3389 user@host` then connect RDP client to localhost:3389
  - Document this as preferred method vs. password-based RDP
- Add credential helper functions for:
  - Storing and retrieving workspace-scoped credentials
  - Resolving credential requirements per operation type
  - Redacting credentials in logs, displays, and saved state
- RDP connection scenarios:
  - SSH tunnel (recommended): No password exposed, encrypted tunnel
  - Direct RDP with password: Only when SSH access not available
  - Consider NLA (Network Level Authentication) for direct RDP

#### 1.3 Shell Injection Prevention
- Status: local shell-heavy helpers, the main remote SSH/SCP assembly paths, and remote deploy script execution now use shared command builders or SSH stdin streaming
- Audit all subprocess calls and SSH command constructions
- Replace shell=True usage with list-based arguments where possible
- Implement proper escaping for unavoidable shell constructions
- Create utility functions for safe command building

#### 1.4 Secure Defaults
- Status: workstation system types no longer auto-enable RDP, and shared SSH helpers now pin host trust to workspace-managed `known_hosts` files
- Review and tighten default configurations
- Ensure secure values for security-related options (firewall, SSH, etc.)
- Add security validation for critical configuration values

#### 1.5 Workspace Location Flag
- Add `--workspace` flag to specify custom base directory for setup state/configuration
- Default base: `~/.config/infra_tools` (replacing current `~/.cache/infra_tools`)
- Subdirectories under the workspace base:
  - `setups/` for persisted setup definitions/state
  - `credentials.json` for saved username/password mappings (at workspace root, not inside `setups/`)
  - `known_hosts` for SSH host keys managed by infra_tools
  - `history/` for optional deployment/setup execution history
- Changing `--workspace` changes the base; all subdirectories and files resolve relative to it
- Use cases: Testing, multi-project setups, separate concerns from system configs
- Existing cache/state compatibility will be intentionally broken; users recreate configs in the new workspace instead of migrating old cache entries
- Credentials must never be duplicated into setup cache/history files; those files can reference usernames but not stored passwords

### Phase 2: Architectural Refactor
#### 2.1 Configuration System Overhaul
- Add explicit validation layer on top of dataclass-based config
- Add configuration versioning for the new workspace-managed state format
- Separate CLI/public configuration from internal/runtime state and persisted workspace state

#### 2.2 Plugin-Based System Types
- Status: built-in plugin registry foundation landed; system-type discovery, metadata defaults, conflict detection, lazy step-builder resolution, and explicit base/composition plugin roles now flow through plugin-owned registrations
- Move current domain directories (e.g., common, security, desktop, web, sync, smb) under a main `plugins/` package
- Plugins define reusable steps, defaults, and optional system types; shared validators and utility code can live outside plugins when broadly reusable
- System types are registered by plugins rather than maintained in a central static list
- Implement automatic plugin discovery from the `plugins/` directory
- Define an explicit plugin contract, for example:
  - plugin metadata and name
  - optional dependencies on other plugins
  - globally registered CLI flags
  - exported steps/tasks
  - default configuration hooks
  - system type registrations
  - plugin-specific validators
- Example plugin split:
  - core/base plugins load first in a fixed order for shared foundations
  - `plugins/workstation` provides desktop and workstation-related steps and system types
  - `plugins/web_server` provides web deployment/server steps and registers `server_web`
  - `plugins/proxmox` provides hosted/container steps and registers `server_proxmox`
- After core/base plugins load, resolve dependent plugins in deterministic order
- Allow a late-load discovery step for simple/lightweight plugins that do not declare dependencies
- Fail fast on plugin conflicts; duplicate plugin names, step names, argument registrations, or system type registrations should raise explicit startup errors
- If a system type needs contributions from multiple capability plugins, define that system type in a separate composition plugin that depends on those capability plugins rather than merging partial system type definitions across plugins
- Benefits: Easier to add new system types, better encapsulation, clearer ownership, less central coupling

#### 2.3 Module Dependencies and Coupling
- Analyze and reduce circular dependencies
- Create clear interfaces between modules
- Extract common functionality into well-defined services

#### 2.4 Remote Execution Refactor
- Status: shared SSH/SCP/rsync command builders now back setup, recall, and remote deploy flows
- Create utility functions for safe SSH/SCP command building with list-based args, implement consistent timeout/retry patterns, add proper error handling and logging
- Use SCP over existing SSH connection for secure transfer of remote setup artifacts and deployment credentials where credentials must reach the target system
- Stage remote credential files under a restrictive temporary path such as `/tmp/infra_tools-creds-*`, write them with `0600`, use them only for the required setup step, and remove them immediately after use with best-effort cleanup on failure paths
- SCP chosen over alternatives (SFTP library, inline credential passing) as the best balance of stability (built on existing SSH infrastructure), security (encrypted transfer, no credentials in process args), and simplicity (no new dependencies, uses subprocess SSH/SCP commands already in use)

### Phase 3: Validation and Type Safety
#### 3.1 Comprehensive Input Validation
- Status: workspace paths, notification targets, credential usernames with ambiguous separators, deploy target hostnames, deploy site/path specs, Samba share specs, SMB mount specs, sync/scrub storage specs, and hosted-node targets are now validated before setup/patch or credential-management flows continue
- Implement validation decorators/middleware for all entry points
- Create reusable validation components for common patterns (hostnames, ports, paths, etc.)
- Add range validation for numeric values
- Implement regex validation for patterned inputs (service names, etc.)

#### 3.2 Type Hint Enhancement
- Expand type hint coverage across public interfaces and new plugin APIs
- Use TypedDict for configuration dictionaries where appropriate
- Implement protocol interfaces for plugin architectures

### Phase 4: Error Handling and Observability

#### 4.1 Structured Logging
- Status: service logging now has a shared `log_event()` helper for stable key=value context, and the webhook receiver plus the CI/CD executor, Node/APT/Ruby/uv/cleanup-maintenance/auto-restart/storage-ops/sync-rsync/xRDP-cleanup services use it for their main event/failure logs; webhook config/server lifecycle plus CI/CD executor config/cleanup/notification, repo sync, script execution, job lifecycle, remote deployment, and rsync lifecycle events now emit structured context too
- Keep human-readable CLI output for interactive setup flows
- Use structured logging for services, helpers, and internal diagnostics where persistent logs are useful
- Implement log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Add contextual information to logs (user, host, operation)
- Implement log rotation and filtering

#### 4.2 Exception Hierarchy
- Create custom exception types for different error categories
- Implement proper exception chaining and context preservation
- Add error codes for machine-readable error handling
- Implement graceful degradation where appropriate

#### 4.3 Monitoring and Metrics
- Add basic metrics collection (operation timing, success rates)
- Add debugging/profiling hooks where useful for long-running helpers/services
- Create diagnostic information collection for troubleshooting failed setup/patch runs

### Phase 5: Testing and Quality Assurance

#### 5.1 Test Strategy — ✅ IN PROGRESS
- 931 tests passing across the codebase
- New tests: `test_credentials.py`, `test_workspace_cli.py`, `test_config.py`, `test_setup_common.py`, `test_plugin_registry.py`, `test_ssh_utils.py`, `test_browser_steps.py`
- **TODO**: Property-based testing, integration tests for common setup scenarios

#### 5.2 Security Testing — ❌ NOT STARTED
- **TODO**: Static analysis (bandit, semgrep), dependency vulnerability checking, fuzz testing

#### 5.3 Code Quality — ❌ NOT STARTED
- **TODO**: Pre-commit hooks, type checking in CI, documentation coverage

## Success Criteria Status

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Password-bearing SSH/login CLI flags removed | ✅ Done |
| 2 | Workspace credentials in `credentials.json` with `0600` permissions | ✅ Done |
| 3 | Password-based features resolve from workspace store | ✅ Done |
| 4 | `shell=True` and unsafe command construction addressed | ⚠️ Partial |
| 5 | Comprehensive input validation for external interfaces | ⚠️ Partial |
| 6 | Structured logging without credential exposure | ⚠️ Partial |
| 7 | Plugin discovery with conflict detection | ⚠️ Partial |
| 8 | Improved performance and reliability | ⚠️ Partial |
| 9 | Enhanced extensibility | ⚠️ Partial |
| 10 | Regression tests for credential/plugin/passwordless behavior | ✅ Done |

## Next Steps
1. ~~Review and approve this plan~~ ✅ Done
2. ~~Define the `credentials` subcommand UX and `credentials.json` schema/file-permission expectations~~ ✅ Done
3. ~~Define the SSH/SCP transfer mechanism for deployment credentials~~ ✅ Decided: SCP over existing SSH connection, temp path `/tmp/infra_tools-creds-*`, `0600` permissions, cleanup on success/failure
4. Expand validation further across more external inputs now that workspace, notification, credential-name, deploy-target, deploy-spec, Samba share, SMB mount, sync/scrub, and hosted-node checks are in place
5. Continue structured logging adoption in remaining long-running services/helpers that still emit free-form diagnostics
6. Establish CI/CD pipeline for automated testing
7. Add security testing (bandit, semgrep, fuzz testing)
8. Implement pre-commit hooks and type checking in CI
9. Implement pre-commit hooks and type checking in CI

---
*This plan will be executed in iterations with regular reviews to ensure alignment with project goals and adjustment based on findings during implementation.*
