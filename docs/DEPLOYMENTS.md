# Deployments and manifests

`infra_tools` deploys a repository with `--deploy DOMAIN GIT_URL`. A repository
can use automatic project-type detection, or place an `infra.json` file at its
root to describe one or more static sites and services explicitly. The manifest
is validated before deployment; an invalid file stops deployment instead of
falling back to automatic detection.

## Basic deployment

```bash
infra_tools setup server_web web.example.com deploy \
  --ruby --node --ssl --ssl-email admin@example.com \
  --deploy web.example.com https://github.com/example/web.git
```

Without a manifest, the repository is classified as Rails, Node, static, or
unknown by the automatic detection rules. Use [`DEPLOYMENT_SAFETY.md`](./DEPLOYMENT_SAFETY.md)
for backup, persistent-state, rollback, and update-policy behavior.

## Manifest shape

The top-level object must contain `version: 1` and a non-empty `components`
array. Component names use lowercase letters, numbers, and hyphens and must be
unique within the file.

### Static site

```json
{
  "version": 1,
  "components": [
    {
      "name": "site",
      "type": "static",
      "domain": "{{domain}}",
      "path": "/",
      "build": ["npm ci", "npm run build"],
      "env": {"PUBLIC_MODE": "production"},
      "output": "dist"
    }
  ]
}
```

`output` is relative to the repository and is served by Nginx after the build.
It must not be absolute or escape the repository. `build` may be one command,
an array of commands, or omitted when the checked-in output is ready to serve.
Build commands run from the repository root, and `env` values are available to
those commands only. Environment variable names must be shell identifiers: a
letter or underscore followed by letters, digits, or underscores. Do not put
secrets in a committed manifest.

### Static site plus API service

```json
{
  "version": 1,
  "components": [
    {
      "name": "site",
      "type": "static",
      "domain": "{{domain}}",
      "output": "frontend/dist",
      "build": "npm ci && npm run build"
    },
    {
      "name": "api",
      "type": "service",
      "domain": "api.{{domain}}",
      "path": "/",
      "build": "server/build.sh",
      "binary": "server/app",
      "port": 8080,
      "env_file": "{{shared_dir}}/.env",
      "health": "/health"
    }
  ]
}
```

Each component owns its domain and URL path. A `{{domain}}` placeholder uses
the domain from `--deploy`; a literal domain does not require one. Service
components are reverse-proxied by Nginx to their loopback `port`. The service
must provide exactly one of `binary` (a repository-relative built artifact) or
`exec` (a command string).

## Service options

In addition to the common fields (`name`, `type`, `domain`, `path`, `build`, and
`env`), a `service` component supports:

- `port`: required integer from 1024 through 65535;
- `binary` or `exec`: exactly one is required;
- `working_dir`: repository-relative directory or a supported template path;
- `env_file`: absolute server path, or a path using deploy-time templates;
- `health`: optional URL path polled on `127.0.0.1:port` after startup; and
- `systemd_unit`: optional repository-relative unit template. Without it,
  infra_tools writes a hardened managed unit.

Supported templates include `{{release_dir}}`, `{{base_dir}}`, `{{name}}`,
`{{service_name}}`, `{{domain}}`, `{{path}}`, `{{web_user}}`, `{{web_group}}`,
`{{port}}`, `{{binary}}`, `{{working_dir}}`, `{{env_file}}`, `{{shared_dir}}`,
and `{{data_dir}}`. Unknown templates fail validation. A health failure emits
a warning after retries but does not abort an otherwise successful deployment.

## Runtime and update behavior

- Manifest deployments build every component on each deployment; they do not
  use incremental builds.
- Existing release files are replaced only after services are stopped. Static
  files are owned by the deployment user.
- Each service receives a dedicated system user and persistent writable state
  under `/var/www/.infra_tools_shared/<app>/<component>`.
- Service state remains outside the release directory, so replacing a release
  does not remove component data.
- `infra_tools patch HOST --deploy ...` reruns the saved deployment with the
  same manifest-aware path. Use `infra_tools deploy PATTERN` to rerun saved
  configurations.

## Validation and troubleshooting

Manifest validation is strict: unknown fields, duplicate names, invalid domains,
unsafe paths, unsupported versions, invalid ports, invalid environment variable
names, and malformed service templates are rejected. Check the remote deployment
output and inspect the generated service when a component does not start:

```text
sudo systemctl status app-<deployment>-<component>.service
sudo journalctl -u app-<deployment>-<component>.service -n 100 --no-pager
```

Replace `<deployment>` and `<component>` with the generated service name.

For Nginx and deployment rollback behavior, see
[`DEPLOYMENT_SAFETY.md`](./DEPLOYMENT_SAFETY.md). For webhook-triggered builds,
see [`CICD.md`](./CICD.md).
