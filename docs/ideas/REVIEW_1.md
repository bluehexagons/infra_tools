# infra_tools Architecture and Security Review Plan

## Overview
This document outlines a plan for major architectural and security improvements to the infra_tools codebase. As this is a major revision, backwards compatibility is not required.

## Primary Focus Areas
1. **Security Hardening** - Eliminate injection vulnerabilities and improve secure handling of sensitive data
2. **Architectural Improvements** - Refactor for better maintainability, testability, and extensibility
3. **Validation Enhancement** - Strengthen input validation throughout the codebase
4. **Error Handling & Logging** - Implement consistent, secure error handling and logging

## Detailed Implementation Plan

### Phase 1: Security Foundation
#### 1.1 Remove Password Command-Line Exposure
- Eliminate password acceptance via command-line arguments
- Implement SSH key-only authentication for remote operations
- Add interactive password prompts when absolutely necessary (with secure input handling)
- Update all related configuration and argument parsing

#### 1.2 Credential Management Strategy
- Implement secure credential storage (keyring or encrypted file) for system passwords
- Support password-free RDP via SSH tunnel (xRDP over SSH):
  - Configure xRDP to not require password (password=ask or empty with PAM)
  - Client connects via SSH tunnel: `ssh -L 3389:localhost:3389 user@host` then connect RDP client to localhost:3389
  - Document this as preferred method vs. password-based RDP
- Add credential helper functions for:
  - Generating secure passwords
  - Retrieving stored credentials
  - Validating credential requirements per operation type
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
- Store: Setup configurations, host metadata, deployment history, SSH known hosts
- Use cases: Testing, multi-project setups, separate concerns from system configs

### Phase 2: Architectural Refactor
#### 2.1 Configuration System Overhaul
- Replace dataclass-based config with pydantic models for automatic validation
- Implement configuration profiles/tiers (development, production, etc.)
- Add configuration versioning and migration capabilities
- Separate public configuration from internal/runtime state

#### 2.2 Plugin-Based System Types
- Move system type definitions from lib/system_types.py to plugin files
- Each system type (e.g., server_web, workstation_desktop) should have its own plugin module
- Plugin files should define: step lists, default configurations, system-specific validators
- Implement plugin discovery mechanism (auto-discover setup_*.py files or explicit plugin directory)
- Example: server_web.py plugin defines web server steps, nginx config, SSL handling, etc.
- Benefits: Easier to add new system types, better encapsulation, clearer ownership

#### 2.3 Module Dependencies and Coupling
- Analyze and reduce circular dependencies
- Implement dependency injection where appropriate
- Create clear interfaces between modules
- Extract common functionality into well-defined services

#### 2.3 Remote Execution Refactor
- Consider: A lightweight wrapper around subprocess with proper list-based args is ~100 lines
- Create utility functions for safe SSH command building with list-based args, implement consistent timeout/ retry patterns, add proper error handling and logging

### Phase 3: Validation and Type Safety
#### 3.1 Comprehensive Input Validation
- Implement validation decorators/middleware for all entry points
- Create reusable validation components for common patterns (hostnames, ports, paths, etc.)
- Add range validation for numeric values
- Implement regex validation for patterned inputs (service names, etc.)

#### 3.2 Type Hint Enhancement
- Ensure 100% type hint coverage
- Use TypedDict for configuration dictionaries where appropriate
- Add runtime type checking in development mode
- Implement protocol interfaces for plugin architectures

### Phase 4: Error Handling and Observability
#### 4.1 Structured Logging
- Replace print statements with structured logging (structlog or similar)
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
- Implement health check endpoints
- Add debugging/profiling hooks
- Create diagnostic information collection

### Phase 5: Testing and Quality Assurance
#### 5.1 Test Strategy
- Implement property-based testing for validation logic
- Add integration tests for common setup scenarios
- Create chaos engineering tests for failure scenarios

#### 5.2 Security Testing
- Add static analysis security scanning (bandit, semgrep)
- Implement dependency vulnerability checking
- Add fuzz testing for input validation
- Create security regression tests

#### 5.3 Code Quality
- Implement pre-commit hooks for formatting and linting
- Add type checking to CI pipeline (mypy or pyright)
- Implement cyclomatic complexity limits
- Add documentation coverage requirements

## Specific Component Plans

### Core Library (lib/)
#### Config Module
- Migrate to pydantic BaseSettings
- Implement environment variable loading
- Add configuration validation rules
- Create configuration templates/examples

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
- Implement connection pooling (if using library)
- Add SFTP support for file transfers (if using library or wrapper)
- Improve error handling and retry logic

### Feature Modules
#### Web Module
- Decouple nginx configuration from deployment logic
- Implement template-based configuration generation
- Improve SSL certificate management

#### Security Module
- Implement firewall rule validation
- Add intrusion detection/prevention integration
- Create security benchmarking capabilities
- Add automated security updating
- Add security event notifications

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

#### patch_setup.py
- Ensure all functionality is moved to `infra_tools.py patch (...)`, `infra_tools.py list (...)`, etc
- Remove in favor of unified entry point

#### Individual Setup Scripts
- Remove in favor of unified entry point (`infra_tools.py setup system_type`)

## Migration Strategy
Since backwards compatibility is not required:
1. Create new implementation in parallel
2. Provide migration documentation
3. Allow side-by-side testing during transition
4. Remove old implementation after validation period

## Success Criteria
1. Zero shell injection vulnerabilities (verified by security scanning)
2. No sensitive data exposed in process lists or logs
3. Comprehensive input validation for all external interfaces
4. Structured, secure logging implementation
5. Clear, documented architecture with well-defined interfaces
6. Improved performance and reliability through better error handling
7. Enhanced extensibility for future feature additions

## Risks and Mitigations
1. **Risk**: Introducing new bugs during refactor
   **Mitigation**: Comprehensive test suite and incremental implementation
   
2. **Risk**: Performance degradation from new abstractions
   **Mitigation**: Benchmarking and optimization during implementation

## Next Steps
1. Review and approve this plan
2. Begin implementation of Phase 1 (Security Foundation)
3. Establish CI/CD pipeline for automated testing
4. Begin writing tests for existing functionality to ensure regression protection

---
*This plan will be executed in iterations with regular reviews to ensure alignment with project goals and adjustment based on findings during implementation.*
