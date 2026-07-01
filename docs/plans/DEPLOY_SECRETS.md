# Deploy Secrets & Optional Components

Status: planned. This is the next step after isolation and manifest support.

The intended shape is simple:

- provision `.env` content from the workspace instead of hand-copying it onto
  servers
- gate optional service components on secret presence
- keep secret transport off the command line and out of world-readable staging
- let build env vary based on whether a component was enabled

This remains a design note only. When implementation starts, the work should be
built on top of the current deployment and manifest code paths:

- `README.md`
- `docs/DEPLOYMENT_SAFETY.md`
- `lib/credentials.py`
- `lib/deployment.py`
- `lib/project_manifest.py`
