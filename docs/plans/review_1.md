# Future Ideas and Enhancements

This file captures potential improvements and follow-up work for infra_tools.

## Completed in Major Revision Branch

- **#79 Self-setup**: Launcher install for `infra_tools` command on PATH, system-wide and per-user
- **#27 Interactive CLI**: Top-level `shell` subcommand with REPL for configuration management
- **#82 Proxmox Notifications**: Native Proxmox webhook notifications via `pvesh`
- **#84 Live LXC Integration Test**: `test_proxmox_live.py` with `INFRA_TOOLS_RUN_LIVE_PROXMOX=1` gating
- **#89 Node version cleanup**: Stale nvm version removal in cleanup maintenance
- **#88 Bundler cleanup** (partial): Cleanup scanning `/var/tmp` for `bundler*` directories
- **#81 Container Lifecycle**: `config`, `reconfigure`, `modify`, `resize-disk` commands in CLI and ProxmoxShell; `get_container_config`, `get_container_pending`, `reconfigure_container`, `modify_container`, `resize_container_disk` in `lib/proxmox_manage`
- **#27 Shell history**: Readline-based persistent history at `~/.local/share/infra_tools/shell_history`
- **#27 Output formatting**: `list --json` (JSON array output) and `info --compact` (one-line summary) in CLI and shell
- **#27 Init file**: `~/.infra_toolsrc` shell startup commands dispatched at shell start
- **#88 /tmp monitoring**: Structured `log_tmp_usage` per temp directory on each cleanup run
- **#88 tmpfiles.d config**: `install_tmpfiles_conf()` deploys `/etc/tmpfiles.d/infra_tools.conf` during bootstrap to auto-age known prefixes via `systemd-tmpfiles-clean`

## Open Issues

### #27: Remaining Interactive CLI Features

- **Autocompletion within shell**: Tab-complete patterns, hosts, vmids, subcommands (requires upstream `readline` integration or custom solution)
- **Configuration templates**: `template list`, `template show`, save/load partial setups as templates
- **Workspace shortcuts**: Quick aliases within shell to switch between workspaces (e.g., `ws prod`, `ws staging`)

### #88: Remaining /tmp Cleanup Work

- Transient build artifacts in `/tmp` from concurrent operations
- tmpfs mount configuration to prevent filling /tmp (`--set-tmpfs-limit SIZE` for bootstrap)
- Alert on /tmp usage threshold (complement to existing root fs low-space alert)

**Approach**:
- Add `/etc/tmpfiles.d/infra_tools.conf` to auto-age and remove aged artifacts
- Implement `--set-tmpfs-limit SIZE` option for bootstrap to configure `/tmp` tmpfs mount size
- Add periodic monitoring via cleanup maintenance to log /tmp usage trends
- Document best practices for tmpfs sizing on orchestration hosts

## Performance & Scalability

- **Configuration search**: `list` and `info` commands scan all saved configs; large workspaces (1000+) may be slow
  - Add indexing or caching layer for frequent patterns
  - Add filtering options (e.g., `list --tags prod --before 2025-01-01`)

- **Proxmox API overhead**: Commands that list/query containers make sequential SSH calls per host
  - Batch operations where possible
  - Async/parallel queries across multiple hosts

## Testing Infrastructure

- **Live Proxmox test**: Currently requires manual `PROXMOX_TEST_HOST` environment setup; could expand to:
  - Container creation/deletion lifecycle
  - Notification delivery verification
  - Multi-host coordination tests

- **CI/CD integration**: Add pre-merge checks for documentation, shell completions, help text consistency

## Documentation & UX

- **Interactive shell guide**: Dedicated tutorial (e.g., `docs/INTERACTIVE_SHELL.md`)
- **Quick-start with launcher**: Beginner-friendly setup guide for new users
- **Error recovery guide**: Common failures (network, SSH, disk space) and recovery steps
- **Workspace management guide**: Best practices for multi-environment setups

## Maintenance

- **Dependency updates**: `uv`, `argcomplete` pinning and update strategy
- **Python version support**: Currently requires 3.10+; could consider backport or security fixes for 3.9
- **Debian version support**: Test on current and LTS releases

## Known Limitations

- **SSH key management**: Currently supports per-host keys; no agent forwarding or multi-key support
- **Credential storage**: Workspace credentials stored in plaintext; consider encryption at rest
- **Network resilience**: SSH connection drops during long operations may leave partial state
- **Concurrency**: Multiple infra_tools processes operating on same workspace could race on saves
