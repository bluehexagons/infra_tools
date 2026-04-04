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
- Audit all subprocess calls and SSH command constructions
- Replace shell=True usage with list-based arguments where possible
- Implement proper escaping for unavoidable shell constructions
- Create utility functions for safe command building

#### 1.4 Secure Defaults
- Review and tighten default configurations
- Ensure secure values for security-related options (firewall, SSH, etc.)
- Add security validation for critical configuration values

#### 1.5 Workspace Location Flag
- Add `--workspace` flag to specify custom directory for setup state/configuration
- Default: `~/.config/infra_tools/setups` (replacing current `~/.cache/infra_tools/setups`)
- Store: Setup configurations, host metadata, deployment history, credentials state, SSH known hosts
- Recommended workspace layout:
  - `setups/` for persisted setup definitions/state
  - `credentials.json` for saved username/password mappings
  - `known_hosts` for SSH host keys managed by infra_tools
  - `history/` for optional deployment/setup execution history
- Use cases: Testing, multi-project setups, separate concerns from system configs
- Existing cache/state compatibility will be intentionally broken; users recreate configs in the new workspace instead of migrating old cache entries
- Credentials must never be duplicated into setup cache/history files; those files can reference usernames but not stored passwords

### Phase 2: Architectural Refactor
#### 2.1 Configuration System Overhaul
- Replace dataclass-based config with pydantic models for automatic validation
- Add configuration versioning for the new workspace-managed state format
- Separate CLI/public configuration from internal/runtime state and persisted workspace state

#### 2.2 Plugin-Based System Types
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
- Create utility functions for safe SSH/SCP command building with list-based args, implement consistent timeout/retry patterns, add proper error handling and logging
- Use SSH/SCP for secure transfer of remote setup artifacts and deployment credentials where credentials must reach the target system
- Stage remote credential files under a restrictive temporary path such as `/tmp/infra_tools-*` or a user-owned runtime temp directory, write them with `0600`, use them only for the required setup step, and remove them immediately after use with best-effort cleanup on failure paths

### Phase 3: Validation and Type Safety
#### 3.1 Comprehensive Input Validation
- Implement validation decorators/middleware for all entry points
- Create reusable validation components for common patterns (hostnames, ports, paths, etc.)
- Add range validation for numeric values
- Implement regex validation for patterned inputs (service names, etc.)

#### 3.2 Type Hint Enhancement
- Expand type hint coverage across public interfaces and new plugin APIs
- Use TypedDict or pydantic models for configuration dictionaries where appropriate
- Implement protocol interfaces for plugin architectures

### Phase 4: Error Handling and Observability
#### 4.1 Structured Logging
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
#### 5.1 Test Strategy
- Implement property-based testing for validation logic
- Add integration tests for common setup scenarios

#### 5.2 Security Testing
- Add static analysis security scanning (bandit, semgrep)
- Implement dependency vulnerability checking
- Add fuzz testing for input validation
- Create security regression tests

#### 5.3 Code Quality
- Implement pre-commit hooks for formatting and linting
- Add type checking to CI pipeline (mypy or pyright)
- Add documentation coverage requirements

## Specific Component Plans

### Core Library (lib/)
#### Config Module
- Migrate to pydantic models appropriate for CLI/workspace state rather than relying on a single dataclass
- Implement environment variable loading
- Add configuration validation rules
- Split configuration responsibilities into distinct models:
  - CLI/request model
  - persisted workspace state model
  - runtime execution model

#### Validation Module
- Expand validation functions with comprehensive test coverage
- Add validation for security-sensitive inputs (SQL-like patterns, shell metacharacters)
- Implement validation composition utilities
- Add custom validator registry

#### Machine State
- Improve container/VM detection logic (auto-detect should be the new default)
- Implement machine capability discovery
- Add caching for expensive detection operations

#### Remote Utils
- Evaluate: Use established SSH library (paramiko) vs. lightweight wrapper around subprocess
- Implement workspace-aware paths (use relative paths from workspace base)
- Replace password-bearing command-line flows with workspace credential resolution and safer transfer mechanisms where credentials must reach the remote host
- Add SFTP support for file transfers (if using library or wrapper)
- Improve error handling and retry logic

### Feature Modules
#### Web Module
- Decouple nginx configuration from deployment logic
- Implement template-based configuration generation
- Improve SSL certificate management

#### Security Module
- Implement firewall rule validation
- Add automated security updating

#### Samba Module
- Improve share permission validation
- Add SMB encryption support
- Implement better audit logging

#### Desktop Module
- Decouple desktop environment installation from configuration
- Improve Flatpak integration
- Implement desktop settings synchronization

### Entry Points
#### infra_tools.py
- Simplify to thin wrapper around functionality
- Implement plugin discovery mechanism
- Add better help and examples generation
- Implement configuration validation before execution
- Load system types and plugin-provided arguments dynamically from discovered plugins
- Add credential management subcommands under `infra_tools.py credentials` with help output for list/remove/set operations

#### patch_setup.py
- Ensure all functionality is moved to `infra_tools.py patch (...)`, `infra_tools.py list (...)`, etc
- Remove in favor of unified entry point

#### Individual Setup Scripts
- Remove in favor of unified entry point (`infra_tools.py setup system_type`)

## Non-Goals
1. Migrate old workspace/cache data into the new layout
2. Add host-scoped or operation-scoped credential storage in this pass
3. Add secret encryption, keyring integration, or external secret managers in this pass
4. Support partial system-type merging across plugins

## Migration Strategy
Since backwards compatibility is not required:
1. Create new implementation in parallel
2. Provide reset/recreation documentation for the new workspace layout and state model
3. Allow side-by-side testing during transition where practical, but do not migrate old cached setup state
4. Remove old implementation after validation period

## Success Criteria
1. Known password-bearing SSH/login CLI flags are removed and setup no longer generates or prints default random login passwords
2. Workspace credentials are stored and resolved through a single source-of-truth `credentials.json` file using per-credential objects and secure `0600` permissions
3. Password-based features that still require credentials can resolve them from the workspace store without inline `username:password` inputs
4. Known `shell=True` and unsafe command-construction hotspots are removed, isolated, or explicitly justified with tests and escaping
5. Comprehensive input validation exists for all external interfaces touched by the refactor
6. Structured logging for services/helpers and human-readable CLI output coexist without exposing credentials in logs or saved state
7. Plugin discovery fails fast on conflicts, loads in deterministic order, and the plugin contract is documented
8. Improved performance and reliability through better error handling
9. Enhanced extensibility for future feature additions
10. Regression tests cover credential redaction, credential resolution, plugin conflict failures, and passwordless account setup behavior

## Risks and Mitigations
1. **Risk**: Introducing new bugs during refactor
   **Mitigation**: Comprehensive test suite and incremental implementation
   
2. **Risk**: Performance degradation from new abstractions
   **Mitigation**: Benchmarking and optimization during implementation

## Next Steps
1. Review and approve this plan
2. Define the `credentials` subcommand UX and `credentials.json` schema/file-permission expectations
3. Define the SSH/SCP transfer mechanism for deployment credentials, including temp-file path and cleanup behavior
4. Define the plugin contract and discovery/registration rules, including explicit conflict detection and load ordering
5. Define composition rules for system-type plugins vs. capability plugins
6. Begin implementation of Phase 1 (Security Foundation)
7. Establish CI/CD pipeline for automated testing
8. Begin writing tests for existing functionality to ensure regression protection

---
*This plan will be executed in iterations with regular reviews to ensure alignment with project goals and adjustment based on findings during implementation.*
