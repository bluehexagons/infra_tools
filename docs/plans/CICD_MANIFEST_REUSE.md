# CI/CD Manifest Reuse

Status: planned. This is the follow-up project for teaching the webhook
CI/CD path to consume `infra.json` instead of only the server-side webhook
scripts.

Why it is separate:

- the current webhook executor is built around one artifact, one remote path,
  and one domain
- the manifest is multi-component and can combine static sites with managed
  services
- remote service install and health polling need a larger rework than a small
  shim

If this work resumes, start from:

- `docs/DEPLOYMENTS.md`
- `docs/CICD.md`
- `lib/project_manifest.py`
- `web/service_tools/cicd_executor.py`
- `lib/deployment.py`
