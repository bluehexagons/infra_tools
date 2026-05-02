# REVIEW_1 Workspace, Credential, and Execution Hardening

This document describes the architecture of the REVIEW_1 revision branch and tracks remaining work and testing.

## Architecture Overview

REVIEW_1 establishes a new foundation for how `infra_tools` stores local state, manages reusable credentials, validates user input, resolves system types, and executes remote setup work. The changes replace the older cache- and wrapper-script-based model with a unified CLI and workspace-scoped runtime model.

### Key Components

- **Unified CLI Surface**: `infra_tools.py` is now the primary entry point; older per-system wrappers removed
- **Workspace-Based State**: State under `~/.config/infra_tools` (or `--workspace` path) with `setups/`, `credentials.json`, `known_hosts`, and `history/`
- **Credential Handling**: Workspace-managed credentials via `infra_tools.py credentials` with `0600` permissions
- **Remote Execution**: Artifacts staged locally, streamed over SSH stdin as tar archive; runtime args in temporary JSON file
- **Plugin-Based System Types**: Automatic discovery from `plugins/` with deterministic dependency resolution
- **Validation and Safer Defaults**: CLI input validation and secure defaults (no generated passwords, workspace-managed SSH `known_hosts`, etc.)
- **Structured Logging**: Service helpers use `key=value` event context for stable operational logs

### Test Coverage

At the time of last review, the test suite passed with 1190 tests. Tests cover:

- Workspace path handling and workspace-aware CLI behavior
- Credential storage and runtime resolution
- Plugin registry behavior and registration
- Remote setup arg-file handling
- Cache/history persistence
- SSH command building and command-safety
- Regression test preventing `shell=True` subprocess usage

## Remaining Work and Testing

### Completed in This Revision

- **#79 Self-setup**: Launcher install for `infra_tools` command on PATH
- **#27 Interactive CLI**: Shell subcommand with REPL and persistent history
- **#82 Proxmox Notifications**: Native webhook notifications
- **#84 Live LXC Integration Test**: `test_proxmox_live.py` with environment gating
- **#89 Node version cleanup**: Stale nvm version removal in cleanup maintenance
- **#88 Bundler cleanup**: Scanning `/var/tmp` for `bundler*` directories
- **#81 Container Lifecycle**: `config`, `reconfigure`, `modify`, `resize-disk` commands
- **#27 Output formatting**: `list --json` and `info --compact`
- **#27 Init file**: `~/.infra_toolsrc` shell startup
- **#88 /tmp monitoring**: Structured `log_tmp_usage` logging
- **#88 tmpfiles.d config**: Auto-aging of known prefixes

### Testing Tasks

- [ ] Full regression test suite passes with 1190+ tests
- [ ] Live Proxmox tests pass with `INFRA_TOOLS_RUN_LIVE_PROXMOX=1` (requires manual `PROXMOX_TEST_HOST` setup)
- [ ] Verify workspace isolation and credential permission (0600)
- [ ] Verify SSH command safety (no `shell=True`)
- [ ] Test credential resolution in Samba shares and SMB mounts
- [ ] Verify plugin discovery works in both local and remote execution contexts
- [ ] Verify sanitized state and history persistence (no credential leaks)

### Known Limitations (Not Blockers)

- **Autocompletion within shell**: Tab-completion requires upstream `readline` integration or custom solution
- **Configuration templates**: Save/load partial setups
- **Workspace shortcuts**: Quick aliases to switch workspaces
- **tmpfs mount configuration**: Prevent filling /tmp with `--set-tmpfs-limit SIZE`
- **Configuration search performance**: Large workspaces (1000+) may be slow; needs indexing/caching
- **Proxmox API overhead**: Sequential SSH calls per host; needs batch operations
- **SSH key management**: Currently supports per-host keys; no agent forwarding or multi-key support
- **Credential encryption**: Workspace credentials stored in plaintext
- **Network resilience**: SSH connection drops may leave partial state
- **Concurrency**: Multiple infra_tools processes may race on workspace saves

## Deferred Follow-Up Work

The following remain reasonable future improvements but are not blockers for this branch:

- Broader type-checking and pre-commit automation
- Expanded integration testing beyond targeted regression suite
- Additional metrics and diagnostics for long-running service workflows
- Documentation enhancements (interactive shell guide, quick-start, error recovery, workspace management)
- Dependency update strategy for `uv` and `argcomplete`
