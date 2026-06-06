# Deploy Isolation

Status: implemented for manifest deploys and the legacy Rails path. The
purpose of this note is to capture the isolation model without repeating the
full design narrative.

Current behavior:

- manifest service components get dedicated runtime users
- persistent state lives under `.infra_tools_shared/<app>/<component>`
- release trees stay owned by `web-deploy`
- legacy Rails services use `rails-<app>` runtime users and the same shared
  persistence root

The live implementation is in:

- `lib/deployment.py`
- `web/cicd_steps.py`
- `lib/systemd_service.py`
- `tests/test_manifest_deploy.py`

`PROJECT_MANIFEST.md` defines the templated fields that consume this model.
