#!/usr/bin/env python3
"""
Webhook Receiver for CI/CD

A secure webhook receiver that accepts GitHub webhooks and triggers CI/CD builds.
Runs as a systemd service and listens on localhost only for security.

Security features:
- HMAC signature verification (X-Hub-Signature-256)
- Localhost-only binding
- Rate limiting via nginx
- Dedicated webhook user with limited permissions

Logs to: /var/log/infra_tools/web/webhook_receiver.log
"""

from __future__ import annotations

import os
import sys
import json
import hmac
import hashlib
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification

# Initialize centralized logger
logger = get_service_logger('webhook_receiver', 'web', use_syslog=True)

# Configuration paths
CONFIG_DIR = "/etc/infra_tools/cicd"
CONFIG_FILE = os.path.join(CONFIG_DIR, "webhook_config.json")
STATE_DIR = "/var/lib/infra_tools/cicd"
JOBS_DIR = os.path.join(STATE_DIR, "jobs")

# Server configuration
DEFAULT_PORT = 8765
WEBHOOK_SECRET_ENV = "WEBHOOK_SECRET"


def verify_github_signature(secret: str, payload: bytes, signature_header: Optional[str]) -> bool:
    """Verify GitHub webhook HMAC signature."""
    if not signature_header:
        return False
    
    # GitHub sends signature as "sha256=<signature>"
    if not signature_header.startswith("sha256="):
        return False
    
    expected_signature = signature_header[7:]  # Remove "sha256=" prefix
    
    # Compute HMAC-SHA256
    computed_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_signature, expected_signature)


def load_config() -> dict:
    """Load webhook configuration from JSON file."""
    if not os.path.exists(CONFIG_FILE):
        logger.warning(f"Configuration file not found: {CONFIG_FILE}")
        return {}
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return {}


def trigger_cicd_job(repo_url: str, ref: str, commit_sha: str, pusher: str) -> bool:
    """
    Trigger CI/CD job by creating a job file for the executor service.
    
    The executor service watches the jobs directory and processes new jobs.
    """
    try:
        os.makedirs(JOBS_DIR, exist_ok=True)
        
        from datetime import datetime
        
        job_data = {
            "repo_url": repo_url,
            "ref": ref,
            "commit_sha": commit_sha,
            "pusher": pusher,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Write job file with commit SHA as filename
        job_file = os.path.join(JOBS_DIR, f"{commit_sha[:8]}.json")
        with open(job_file, 'w') as f:
            json.dump(job_data, f, indent=2)
        
        logger.info(f"Created CI/CD job: {job_file}")
        
        # Trigger executor service to process the new job
        result = subprocess.run(
            ['systemctl', 'start', 'cicd-executor.service'],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.warning(f"Failed to trigger executor service: {result.stderr}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create CI/CD job: {e}")
        return False


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for GitHub webhooks."""
    
    # Suppress default logging (we use our own logger)
    def log_message(self, format, *args):
        pass
    
    def do_POST(self):
        """Handle POST requests (GitHub webhooks)."""
        if self.path != '/webhook':
            self.send_error(404, "Not Found")
            return
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        # Get webhook secret from environment
        secret = os.environ.get(WEBHOOK_SECRET_ENV)
        if not secret:
            logger.error("WEBHOOK_SECRET environment variable not set")
            self.send_error(500, "Server Configuration Error")
            return
        
        # Verify signature
        signature = self.headers.get('X-Hub-Signature-256')
        if not verify_github_signature(secret, body, signature):
            logger.warning(f"Invalid signature from {self.client_address[0]}")
            self.send_error(403, "Invalid Signature")
            return
        
        # Parse JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            self.send_error(400, "Invalid JSON")
            return
        
        # Get event type
        event_type = self.headers.get('X-GitHub-Event', 'unknown')
        
        # Handle push events
        if event_type == 'push':
            repo_url = payload.get('repository', {}).get('clone_url', '')
            ref = payload.get('ref', '')
            commit_sha = payload.get('after', '')
            pusher = payload.get('pusher', {}).get('name', 'unknown')
            
            logger.info(f"Received push event: repo={repo_url}, ref={ref}, sha={commit_sha[:8]}")
            
            # Load configuration to check if this repo is configured
            config = load_config()
            repos = config.get('repositories', [])
            
            # Find matching repository configuration
            repo_config = None
            for repo in repos:
                if repo.get('url') == repo_url:
                    repo_config = repo
                    break
            
            if not repo_config:
                logger.info(f"Repository not configured: {repo_url}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ignored", "reason": "repository not configured"}).encode())
                return
            
            # Check if the branch matches configured branches
            branch = ref.replace('refs/heads/', '')
            configured_branches = repo_config.get('branches', ['main', 'master'])
            
            if branch not in configured_branches:
                logger.info(f"Branch not configured: {branch}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ignored", "reason": "branch not configured"}).encode())
                return
            
            # Trigger CI/CD job
            success = trigger_cicd_job(repo_url, ref, commit_sha, pusher)
            
            if success:
                logger.info(f"CI/CD job triggered for {repo_url} @ {commit_sha[:8]}")
                self.send_response(202)  # Accepted
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "accepted", "commit": commit_sha[:8]}).encode())
            else:
                logger.error(f"Failed to trigger CI/CD job")
                self.send_error(500, "Failed to trigger job")
        
        elif event_type == 'ping':
            # Handle ping events (sent when webhook is first created)
            logger.info("Received ping event")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "pong"}).encode())
        
        else:
            # Ignore other event types
            logger.info(f"Ignored event type: {event_type}")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ignored", "reason": f"event type {event_type} not supported"}).encode())
    
    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_error(404, "Not Found")


def main():
    """Main function to run the webhook receiver server."""
    logger.info("Starting webhook receiver")
    
    # Get port from environment or use default
    port = int(os.environ.get('WEBHOOK_PORT', DEFAULT_PORT))
    
    # Verify webhook secret is configured
    if not os.environ.get(WEBHOOK_SECRET_ENV):
        logger.error(f"{WEBHOOK_SECRET_ENV} environment variable not set")
        return 1
    
    # Create jobs directory if it doesn't exist
    os.makedirs(JOBS_DIR, exist_ok=True)
    
    # Start HTTP server (bind to localhost only for security)
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, WebhookHandler)
    
    logger.info(f"Webhook receiver listening on http://127.0.0.1:{port}")
    logger.info("Server is ready to accept webhooks")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook receiver")
        httpd.shutdown()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
