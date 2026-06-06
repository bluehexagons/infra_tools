# Developer Tool Ownership Follow-Up

The ownership bug described in the old draft is now handled in code. This note
keeps only the remaining follow-up work so the larger design discussion does
not stay duplicated across the docs tree.

## Current Direction

- Workstation tool installs should target the created login user.
- CI/CD build jobs should target the dedicated `webhook` user.
- App servers should stay minimal and only install runtime dependencies that a
  deployed service explicitly needs.

## Remaining Work

- Add a first-class `ToolOwner` or similar config concept for login, build,
  and runtime owners.
- Teach `--build-server` to install Node, uv, Ruby, and related toolchains for
  the build job user when those project types are built there.
- Make deploy manifests declare build-time and runtime requirements separately.

## Relevant Code

- `web/service_tools/auto_update_node.py`
- `web/service_tools/auto_update_ruby.py`
- `web/service_tools/auto_update_uv.py`
- `web/cicd_steps.py`
- `lib/update_policy.py`
