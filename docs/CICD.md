# CI/CD Webhook System

The infra_tools CI/CD system provides secure webhook-based continuous integration and deployment for your applications. It receives GitHub webhooks, clones repositories, runs build/test scripts, and deploys applications automatically.

## Architecture

```
GitHub Webhook → Cloudflare Tunnel → Nginx (rate limiting) → Webhook Receiver → CI/CD Executor
                                                                      ↓
                                                              Job Queue (filesystem)
                                                                      ↓
                                                              Git Clone → Build → Test → Deploy
```

## Components

### 1. Webhook Receiver (`webhook-receiver.service`)

- **Purpose**: Accept and validate GitHub webhooks
- **Port**: 8765 (localhost only)
- **User**: webhook (dedicated system user)
- **Security**: 
  - HMAC-SHA256 signature verification
  - Localhost-only binding
  - Rate limiting via nginx (10 req/min per IP)
- **Logs**: `/var/log/infra_tools/web/webhook_receiver.log` (via journald)

### 2. CI/CD Executor (`cicd-executor.service`)

- **Purpose**: Process CI/CD jobs triggered by webhooks
- **Type**: One-shot service (triggered per job)
- **User**: webhook
- **Workspace**: `/var/lib/infra_tools/cicd/workspaces/`
- **Logs**: 
  - Service logs: `/var/log/infra_tools/web/cicd_executor.log`
  - Build logs: `/var/lib/infra_tools/cicd/logs/`

### 3. Nginx Reverse Proxy

- **Purpose**: Rate limiting and secure routing
- **Endpoint**: `/webhook` (exposed via Cloudflare tunnel)
- **Rate limit**: 10 requests per minute per IP, burst of 5
- **Configuration**: `/etc/nginx/conf.d/webhook.conf`

## Setup

### Automatic Setup (Recommended)

Add `--cicd` flag to your setup script:

```bash
python3 setup_server_web.py example.com --cicd
```

Or use patch_setup to add CI/CD to existing server:

```bash
python3 patch_setup.py example.com --cicd
```

### Manual Setup

If you need to set up manually:

```python
from web.cicd_steps import (
    install_cicd_dependencies,
    create_cicd_user,
    create_cicd_directories,
    generate_webhook_secret,
    create_default_webhook_config,
    create_webhook_receiver_service,
    create_cicd_executor_service,
    configure_nginx_for_webhook,
    update_cloudflare_tunnel_for_webhook
)

# Run all setup steps
install_cicd_dependencies(config)
create_cicd_user(config)
create_cicd_directories(config)
generate_webhook_secret(config)
create_default_webhook_config(config)
create_webhook_receiver_service(config)
create_cicd_executor_service(config)
configure_nginx_for_webhook(config)
update_cloudflare_tunnel_for_webhook(config)
```

## Configuration

### Repository Configuration

Edit `/etc/infra_tools/cicd/webhook_config.json`:

```json
{
  "repositories": [
    {
      "url": "https://github.com/yourusername/yourrepo.git",
      "branches": ["main", "develop"],
      "scripts": {
        "install": "scripts/ci-install.sh",
        "build": "scripts/ci-build.sh",
        "test": "scripts/ci-test.sh",
        "deploy": "scripts/ci-deploy.sh"
      }
    }
  ]
}
```

### Script Order

Scripts run in this order:
1. **install**: Install dependencies (npm install, bundle install, etc.)
2. **build**: Build application (compile, bundle, etc.)
3. **test**: Run tests
4. **deploy**: Deploy application (restart services, etc.)

All scripts are **optional**. If a script path is not specified, that stage is skipped.

### Script Paths

- **Absolute paths**: Used as-is (e.g., `/opt/scripts/deploy.sh`)
- **Relative paths**: Resolved relative to repository root (e.g., `scripts/build.sh`)

### Script Requirements

Each script should:
- Be executable by the `webhook` user
- Exit with code 0 on success, non-zero on failure
- Output to stdout/stderr (captured in logs)
- Be idempotent (safe to run multiple times)

### Example Scripts

**scripts/ci-install.sh**:
```bash
#!/bin/bash
set -e
npm ci
```

**scripts/ci-build.sh**:
```bash
#!/bin/bash
set -e
npm run build
```

**scripts/ci-test.sh**:
```bash
#!/bin/bash
set -e
npm test
```

**scripts/ci-deploy.sh**:
```bash
#!/bin/bash
set -e
sudo systemctl restart myapp.service
```

## GitHub Webhook Configuration

1. **Get webhook secret**:
   ```bash
   sudo cat /etc/infra_tools/cicd/webhook_secret
   ```

2. **Configure GitHub webhook**:
   - Go to repository Settings → Webhooks → Add webhook
   - Payload URL: `https://webhook.yourdomain.com/webhook`
   - Content type: `application/json`
   - Secret: Paste the webhook secret
   - Events: Select "Just the push event"
   - Active: ✓ Enabled

3. **Test webhook**:
   - GitHub sends a ping event when you save
   - Check logs: `sudo journalctl -u webhook-receiver.service -f`

## Cloudflare Tunnel Setup

See [webhook_cloudflare_setup.md](../web/config/webhook_cloudflare_setup.md) for detailed Cloudflare configuration.

Quick version:

1. Edit `/etc/cloudflared/config.yml`:
   ```yaml
   ingress:
     - hostname: webhook.yourdomain.com
       service: http://localhost:8080
   ```

2. Add DNS record in Cloudflare:
   - Type: CNAME
   - Name: webhook
   - Target: <tunnel-id>.cfargotunnel.com

3. Restart tunnel:
   ```bash
   sudo systemctl restart cloudflared.service
   ```

## Security

### Authentication

- **HMAC-SHA256 verification**: All webhooks must include valid `X-Hub-Signature-256` header
- **Secret rotation**: Regenerate secret and update GitHub webhook configuration:
  ```bash
  sudo rm /etc/infra_tools/cicd/webhook_secret
  sudo systemctl restart webhook-receiver.service
  sudo cat /etc/infra_tools/cicd/webhook_secret  # Update in GitHub
  ```

### Rate Limiting

- **Nginx**: 10 requests per minute per IP address
- **Burst**: Up to 5 requests can burst beyond the rate limit
- **Response**: HTTP 429 (Too Many Requests) when limit exceeded

### Network Isolation

- Webhook receiver binds to `127.0.0.1` only
- No direct external access possible
- All traffic must go through nginx reverse proxy
- Nginx only accepts connections from Cloudflare tunnel (localhost)

### User Isolation

- Dedicated `webhook` system user
- No login shell (`/usr/sbin/nologin`)
- Minimal permissions (read-only on most files)
- Write access only to job queue and workspaces

### Systemd Hardening

- `NoNewPrivileges=true`: Cannot gain new privileges
- `PrivateTmp=true`: Private /tmp directory
- `ProtectSystem=strict`: Most of filesystem read-only
- `ProtectHome=true`: No access to user home directories
- `ReadWritePaths=/var/lib/infra_tools/cicd`: Explicit write access

## Monitoring

### Check Service Status

```bash
# Webhook receiver
sudo systemctl status webhook-receiver.service

# Check if receiver is listening
sudo ss -tlnp | grep 8765

# View logs
sudo journalctl -u webhook-receiver.service -f
sudo journalctl -u cicd-executor.service -f
```

### View Build Logs

```bash
# List recent builds
ls -lh /var/lib/infra_tools/cicd/logs/

# View specific build log
cat /var/lib/infra_tools/cicd/logs/<commit-sha>.log
```

### Check Pending Jobs

```bash
# List pending jobs
ls -lh /var/lib/infra_tools/cicd/jobs/
```

### Test Webhook Endpoint

```bash
# Health check (should return "OK")
curl http://localhost:8765/health

# Via nginx
curl http://localhost:8080/webhook/health
```

## Troubleshooting

### Webhook Not Triggering

1. **Check webhook receiver is running**:
   ```bash
   sudo systemctl status webhook-receiver.service
   ```

2. **Check GitHub webhook deliveries**:
   - Go to repository Settings → Webhooks
   - Click on your webhook
   - Check "Recent Deliveries" tab
   - Look for response code (should be 202)

3. **Check logs for signature errors**:
   ```bash
   sudo journalctl -u webhook-receiver.service | grep -i signature
   ```

4. **Verify secret matches**:
   ```bash
   # Server secret
   sudo cat /etc/infra_tools/cicd/webhook_secret
   # Should match GitHub webhook secret
   ```

### Build Failing

1. **Check executor logs**:
   ```bash
   sudo journalctl -u cicd-executor.service -n 100
   ```

2. **Check build logs**:
   ```bash
   cat /var/lib/infra_tools/cicd/logs/<commit-sha>.log
   ```

3. **Verify script permissions**:
   ```bash
   ls -l /var/lib/infra_tools/cicd/workspaces/<repo>/scripts/
   ```

4. **Test script manually**:
   ```bash
   sudo -u webhook bash /var/lib/infra_tools/cicd/workspaces/<repo>/scripts/ci-build.sh
   ```

### Repository Clone Failing

1. **Check git is installed**:
   ```bash
   git --version
   ```

2. **Test git access as webhook user**:
   ```bash
   sudo -u webhook git clone <repo-url> /tmp/test-clone
   ```

3. **For private repos**, configure deploy keys:
   ```bash
   sudo -u webhook ssh-keygen -t ed25519 -C "webhook@yourserver"
   cat /home/webhook/.ssh/id_ed25519.pub  # Add to GitHub deploy keys
   ```

### Rate Limiting Issues

If legitimate traffic is being rate limited:

1. **Check nginx configuration**:
   ```bash
   cat /etc/nginx/conf.d/webhook.conf
   ```

2. **Adjust rate limit** (edit `/etc/nginx/conf.d/webhook.conf`):
   ```nginx
   limit_req_zone $binary_remote_addr zone=webhook_limit:10m rate=20r/m;  # Increase to 20/min
   ```

3. **Reload nginx**:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

## Notifications

The CI/CD system integrates with the infra_tools notification system. Configure notifications in your setup:

```python
config = SetupConfig(
    # ... other config ...
    notification_configs=[{
        "type": "discord",
        "webhook_url": "https://discord.com/api/webhooks/..."
    }]
)
```

Notifications are sent for:
- **Build success**: Green notification with commit info
- **Build failure**: Red notification with error reason
- **System errors**: Red notification for configuration issues

## Advanced Configuration

### Custom Port

To change the webhook receiver port, edit `/etc/systemd/system/webhook-receiver.service`:

```ini
Environment="WEBHOOK_PORT=9000"
```

Then update nginx configuration and restart services.

### Multiple Repositories

Add multiple repositories to `/etc/infra_tools/cicd/webhook_config.json`:

```json
{
  "repositories": [
    {
      "url": "https://github.com/user/repo1.git",
      "branches": ["main"],
      "scripts": { "build": "make" }
    },
    {
      "url": "https://github.com/user/repo2.git",
      "branches": ["main", "staging"],
      "scripts": { 
        "install": "npm ci",
        "build": "npm run build",
        "test": "npm test"
      }
    }
  ]
}
```

### Branch-Specific Scripts

Currently, all branches use the same scripts. To implement branch-specific builds, use conditional logic in your scripts:

```bash
#!/bin/bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ "$BRANCH" = "main" ]; then
    npm run build:production
else
    npm run build:staging
fi
```

## Performance Considerations

- **Concurrent builds**: Each job runs sequentially to avoid resource contention
- **Workspace reuse**: Repositories are cloned once and updated with `git pull`
- **Build timeout**: Scripts timeout after 1 hour (configurable in `cicd_executor.py`)
- **Log retention**: Consider setting up log rotation for `/var/lib/infra_tools/cicd/logs/`

## Backup and Maintenance

### Backup Configuration

Include in your backups:
- `/etc/infra_tools/cicd/webhook_config.json` (repository configuration)
- `/etc/infra_tools/cicd/webhook_secret` (webhook secret)

### Log Rotation

Create `/etc/logrotate.d/infra_tools_cicd`:

```
/var/lib/infra_tools/cicd/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 webhook webhook
}
```

### Workspace Cleanup

Workspaces accumulate over time. Clean up old builds:

```bash
# Remove workspaces older than 30 days
find /var/lib/infra_tools/cicd/workspaces -type d -mtime +30 -exec rm -rf {} +

# Or manually remove specific workspace
sudo rm -rf /var/lib/infra_tools/cicd/workspaces/<repo-name>
```

## See Also

- [Logging Documentation](LOGGING.md) - Centralized logging system
- [Cloudflare Tunnel Setup](../web/config/webhook_cloudflare_setup.md) - Cloudflare configuration
- [GitHub Webhooks Documentation](https://docs.github.com/en/webhooks) - Official GitHub docs
