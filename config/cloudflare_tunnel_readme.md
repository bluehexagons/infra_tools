# Cloudflare Tunnel Configuration

This directory is preconfigured for cloudflared setup.

## Automated Setup

Run the automated setup script to configure your Cloudflare tunnel:

```bash
sudo setup-cloudflare-tunnel
```

This script will:
1. Install cloudflared (if not installed)
2. Guide you through Cloudflare authentication
3. Create a tunnel
4. Discover configured sites from nginx
5. Generate config.yml automatically
6. Install and start the tunnel service

## Manual Configuration

If you prefer manual setup or need to customize:

1. Install cloudflared:
   ```
   wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   ```

2. Authenticate with Cloudflare:
   ```
   cloudflared tunnel login
   ```

3. Create a tunnel:
   ```
   cloudflared tunnel create <tunnel-name>
   ```

4. Create config.yml in this directory with your tunnel configuration.

5. Install and start the tunnel service:
   ```
   cloudflared service install
   systemctl start cloudflared
   systemctl enable cloudflared
   ```

## Configuration Template

The config.yml should look like:

```yaml
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json

ingress:
  - hostname: example.com
    service: http://localhost:80
  - hostname: api.example.com
    service: http://localhost:80
  - service: http_status:404
```

## State File

The automated setup script saves its state to `/etc/cloudflared/tunnel-state.json`.
This allows you to re-run the script to update the configuration when you add new sites.

For more information: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
