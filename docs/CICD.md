# CI/CD Webhook System

Use `--cicd` during `setup` or `patch` to install the webhook receiver and
executor. Repository-specific scripts live in
`/etc/infra_tools/cicd/webhook_config.json`.

Example setup:

```bash
infra-tools setup server_web ci.example.com deploy \
  --cicd --ssl --ssl-email admin@example.com
```

After setup, edit the generated configuration and add a GitHub webhook. The
secret is generated once and stored root-only at
`/etc/infra_tools/cicd/webhook_secret`; the systemd environment file is
`/etc/infra_tools/cicd/webhook.env`.

## Build and app server topology

The build server runs the webhook receiver and builds as the dedicated
`webhook` user. An app server only needs nginx, rsync, and the restricted
`deploy` account. The build server pushes artifacts over SSH; it does not need
root access on the app server.

Set up the app server first:

```bash
infra-tools setup server_web app.example.com deploy \
  --app-server --ssl --ssl-email admin@example.com
```

For a provisioned VM, keep the OS and language tooling on SSD-backed root
storage and mount the bulk disk directly at the CI state directory. A nominal
4 TB disk provides about 3.64 TiB before pool overhead, so this example requests
3500 GiB rather than assuming the full advertised capacity is allocatable:

```bash
infra-tools setup server_web 192.168.1.60 deploy \
  --provision-on pve1 --hostname build \
  --memory 16G --cores 8 \
  --storage root local-lvm 96G \
  --disk-ssd root --disk-discard root --disk-backup root \
  --storage cicd-data ts1-storage 3500G \
  --storage-mount cicd-data /var/lib/infra_tools/cicd ext4 empty \
  --no-disk-ssd cicd-data --disk-discard cicd-data --disk-backup cicd-data \
  --build-server --node --python --go
```

Replace the address, Proxmox host, memory, and CPU values for the environment.
Run the same command with `--dry-run` first. The `ts1-storage` pool must support
Proxmox VM disk images and report at least the requested free capacity. The
mount is fail-closed: setup prepares only the newly attached blank disk and
will not fall back to putting builds on the root volume. `--build-server`
already includes the webhook receiver and executor, so adding `--cicd` is
supported but redundant. The explicit per-device flags let reruns retain SSD
emulation only for the SSD-backed root while reconciling discard and Proxmox
backup inclusion on both disks.

For an existing Debian server rather than a newly provisioned VM, omit the
`--provision-on`, capacity, and `--storage*` flags and mount the bulk disk at
`/var/lib/infra_tools/cicd` before setup.

Bootstrap the build server once without deployment targets so its managed
runtime and workspace exist. The storage-aware command above already performs
this phase. Then connect the two saved setups from the controller:

```bash
infra-tools cicd connect 192.168.1.60 app.example.com
```

Saved host names, friendly `--name` values, and exact tags are accepted. If the
controller does not already trust the app server, the command displays its SSH
fingerprint for independent verification. Non-interactive automation can pin
that verified identity explicitly:

```bash
infra-tools cicd connect 192.168.1.60 app.example.com \
  --target-name production \
  --fingerprint SHA256:REPLACE_WITH_VERIFIED_FINGERPRINT
```

The command validates both saved roles, transfers only the public half of the
build deploy key, deduplicates the app server's `authorized_keys`, installs the
verified host key and target definition atomically on the build server, and
tests SSH as the unprivileged `webhook` build user. It is safe to rerun. Inspect
or retest connections with:

```bash
infra-tools cicd status 192.168.1.60
infra-tools cicd test 192.168.1.60 app.example.com
```

The target entries default to the `deploy` user, SSH port 22, and `/var/www`.
Use `cicd connect --port` or `--base-dir` when a target differs. The target name
used by a repository must match its JSON key. A custom base directory must
already exist as a real directory and be writable by the `deploy` account.

## Repository configuration

Edit `/etc/infra_tools/cicd/webhook_config.json` on the build server. Each
repository entry selects accepted branches and scripts. A remote deployment
uses `deploy_target` (a key from `deploy_targets.json`) and an optional
`deploy_spec` (`domain` or `domain/path`):

```json
{
  "repositories": [
    {
      "url": "https://github.com/example/site.git",
      "branches": ["main"],
      "deploy_target": "app.example.com",
      "deploy_spec": "www.example.com/",
      "scripts": {
        "install": "scripts/install.sh",
        "build": "scripts/build.sh",
        "test": "scripts/test.sh",
        "deploy": "scripts/deploy.sh"
      }
    }
  ]
}
```

`install`, `build`, and `test` run in a fresh, commit-pinned workspace as
`webhook`. When `deploy_target` is present, artifacts are pushed with rsync,
nginx configuration is refreshed, and the optional deploy script is streamed
to the target directory. Without `deploy_target`, the optional deploy script
runs locally on the build server. Use repository URLs without embedded
credentials; the executor rejects credential-bearing URLs.

After changing the JSON, the next signed push uses the new settings. A ping
event only verifies webhook connectivity and does not build a repository.

## Security and execution boundaries

- the receiver is localhost-only behind Nginx; expose it through Cloudflare
  Tunnel when that option is configured
- webhook signatures are verified with the stored secret
- webhook bodies are capped at 1 MiB and push fields are validated before queueing
- the executor uses a fresh clone with Git hooks disabled, then checks out the
  signed commit SHA only after verifying it is reachable from the configured
  branch
- repository workspaces include a URL digest, preventing same-name repositories
  from sharing a checkout
- HTTP repository URLs with embedded credentials are rejected so secrets cannot
  leak through queue files or build logs; use the configured Git credential helper
- app-server privilege is exposed only through the validating
  `infra-tools-deploy-admin` helper; the deploy account has no wildcarded root
  `rm`, `mkdir`, or `touch` access
- build logs live under `/var/lib/infra_tools/cicd/logs/`
- build scripts run as the dedicated `webhook` user
- `--build-server --node` and `--build-server --python` bootstrap the build
  toolchains for that user
- the receiver writes one bounded job file and the path unit starts the
  executor, so the receiver does not need systemd or polkit privileges
- jobs are consumed after one attempt, including malformed or failed jobs, so
  one bad payload cannot retrigger forever
- delivery IDs are not yet persisted, so a repeated valid GitHub delivery can
  create another job for the same commit; monitor webhook retries until delivery
  idempotency is implemented

Quick checks:

```bash
sudo systemctl status webhook-receiver.service
sudo journalctl -u webhook-receiver.service -f
sudo journalctl -u cicd-executor.service -f
sudo systemctl status cicd-executor.path
curl -fsS http://127.0.0.1:8080/webhook/health
```

Run `patch` on existing app servers to apply the deploy sudo policy and install
the privileged helper. The helper validates target names and paths before
allowing the deploy account to update an app server.

If you need the full setup flow or command syntax, use
[Command-line reference](./COMMAND_LINE.md) and
[Cloudflare tunnels](./CLOUDFLARE.md).
