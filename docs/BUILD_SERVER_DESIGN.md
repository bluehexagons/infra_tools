# Build Server / App Server Split

This is a short reference for the CI/CD split that now lives in code.
For current usage and flags, see [CICD.md](./CICD.md) and
[COMMAND_LINE.md](./COMMAND_LINE.md).

## What Is Implemented

- `--build-server` provisions the dedicated `webhook` build host and deploy targets.
- `--app-server` provisions a minimal nginx/runtime host.
- `--deploy-target` points the build server at one or more app servers.
- Build jobs run as `webhook` with state under `/var/lib/infra_tools/cicd`.
- App servers receive built artifacts and nginx config, not the full build toolchain.

## Code Locations

- `web/build_server_steps.py`
- `web/app_server_steps.py`
- `web/cicd_steps.py`
- `web/service_tools/cicd_executor.py`
- `lib/arg_parser.py`

## Keep This Short

This document is intentionally brief. The detailed behavior belongs in code and
the operational docs above, not in a second long design narrative.
