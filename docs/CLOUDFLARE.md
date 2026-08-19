# Cloudflare tunnels

`--cloudflare` prepares a web host to use Cloudflare Tunnel as its public edge.
It is a preconfiguration step; it does not authenticate to Cloudflare or create
a tunnel by itself.

## Prepare a host

```bash
infra-tools setup server_web example.com deploy \
  --cloudflare \
  --deploy example.com https://github.com/example/site.git
```

The setup flow:

- installs or enables UFW with default-deny incoming policy and rate-limited SSH access;
- removes public 80/tcp and 443/tcp firewall allowances;
- configures Nginx to trust Cloudflare source ranges;
- creates `/etc/cloudflared/README.md`; and
- installs `/usr/local/bin/setup-cloudflare-tunnel`.

Because the Cloudflare edge provides public HTTPS, Nginx serves the tunnel
origin over local HTTP without forcing an HTTP-to-HTTPS redirect. Proxied
applications still receive `X-Forwarded-Proto: https` so they generate secure
external URLs correctly. Keep SSH reachable through your management network
before enabling the firewall changes.

## Create or update a tunnel

Run the helper interactively on the configured host:

```bash
sudo setup-cloudflare-tunnel
```

The helper installs `cloudflared` from Cloudflare's signed APT repository when needed, runs Cloudflare authentication,
creates or reuses a tunnel, discovers hostnames from enabled Nginx sites, writes
`/etc/cloudflared/config.yml`, and can install and enable the `cloudflared`
systemd service. Tunnel credentials and state are stored under
`/etc/cloudflared` with restrictive permissions.

Generated tunnel and Nginx configurations are validated before activation. A
non-interactive refresh compares complete hostname/origin entries, repairs a
missing or invalid config, and verifies that the service is active; it reports
failure when the service cannot be started instead of claiming success.

After adding or removing an Nginx site, rerun the helper to refresh ingress
entries. A setup or patch run with `--cloudflare` also attempts a non-interactive
refresh when an existing tunnel state file is present.

Verify the service and generated routes:

```bash
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -n 100 --no-pager
sudo sed -n '1,160p' /etc/cloudflared/config.yml
```

Point each hostname at the tunnel in Cloudflare DNS/Zero Trust. The generated
ingress uses `http://localhost:80`; keep the catch-all `http_status:404` rule
last. See the generated `/etc/cloudflared/README.md` for manual configuration
steps.

## Webhooks and direct services

For a CI/CD webhook, add an ingress entry for the webhook hostname that points
to the local receiver port, then configure the matching GitHub webhook secret.
The [CI/CD guide](./CICD.md) covers signature validation and the receiver
service.

Cloudflare Tunnel does not proxy UDP. An Antistatic deployment therefore keeps
its direct UDP 3478 STUN access (and any required direct TCP service port) even
when `--cloudflare` is enabled; the public IP must remain reachable for those
ports. See [Antistatic services](./ANTISTATIC.md).

## Limitations and recovery

- `--cloudflare` changes firewall and Nginx behavior; do not use it until the
  tunnel path and SSH management route are ready. SSH is rate-limited with UFW;
  add a management-network-specific rule separately if your policy needs one.
- Tunnel creation requires an interactive browser login and Cloudflare account
  access; unattended setup cannot create the initial tunnel.
- If a tunnel is unavailable, inspect `cloudflared` and Nginx journals and use
  the host's local port 80 for origin testing.
- To stop using the tunnel, restore the desired 80/443 firewall policy and
  remove or disable the Cloudflare-specific Nginx config after validating the
  replacement configuration.
