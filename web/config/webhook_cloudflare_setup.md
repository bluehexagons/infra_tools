# Cloudflare Tunnel Configuration for Webhook

To expose the webhook endpoint over your Cloudflare tunnel, add the following ingress rule to your tunnel configuration:

## Configuration

Edit `/etc/cloudflared/config.yml` and add:

```yaml
ingress:
  # Webhook endpoint (add this before catch-all rule)
  - hostname: webhook.yourdomain.com
    service: http://localhost:8080
    
  # ... other ingress rules ...
  
  # Catch-all rule (must be last)
  - service: http_status:404
```

## DNS Configuration

Create a DNS record in Cloudflare:

- Type: CNAME
- Name: webhook
- Target: <your-tunnel-id>.cfargotunnel.com
- Proxy status: Proxied (orange cloud)

## GitHub Webhook Configuration

1. Go to your repository settings on GitHub
2. Navigate to: Settings → Webhooks → Add webhook
3. Configure:
   - Payload URL: `https://webhook.yourdomain.com/webhook`
   - Content type: `application/json`
   - Secret: Use the secret from `/etc/infra_tools/cicd/webhook_secret`
   - SSL verification: Enable SSL verification
   - Events: Select "Just the push event" or customize
   - Active: ✓ Enabled

## Testing

After configuration, GitHub will send a ping event. Check:

```bash
# Check webhook receiver logs
sudo journalctl -u webhook-receiver.service -f

# Check webhook receiver status
sudo systemctl status webhook-receiver.service

# Test health endpoint
curl http://localhost:8765/health
```

## Security Notes

- The webhook receiver only listens on localhost (127.0.0.1)
- All external access must go through nginx reverse proxy
- Nginx rate limiting: 10 requests per minute per IP
- HMAC-SHA256 signature verification for all webhooks
- Dedicated 'webhook' user with limited permissions
