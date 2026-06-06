# Project Manifest (`infra.json`)

Status: implemented. The manifest loader, validation, and manifest deploy path
live in code, so this note is intentionally short and serves as a pointer.

`infra.json` is the repo-side contract for deploys:

- it can describe multiple components in one repository
- `static` components build files for nginx to serve
- `service` components install a systemd unit and proxy through nginx
- deploy-time `{{...}}` templating is supported for runtime paths and unit
  content

Where to look in code:

- `lib/project_manifest.py`
- `lib/deployment.py`
- `tests/test_project_manifest.py`
- `tests/test_manifest_deploy.py`

The remaining open question is CI/CD reuse of the same manifest. That future
work is tracked separately in `CICD_MANIFEST_REUSE.md`.
