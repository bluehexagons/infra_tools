# Build Server / App Server Architecture Design

## Overview

This document describes the implementation of separate build servers and lightweight application servers for infra_tools CI/CD.

## Goals

1. Build servers handle all compilation, asset building, and nginx configuration
2. App servers are lightweight - only nginx and runtime dependencies
3. Single command syntax for setting up both server types
4. Build server can add/remove/update sites on app servers remotely

## Command-Line Interface

### Build Server Setup

```bash
# Set up a build server with CI/CD and build tools
python3 setup_server_web.py build.example.com --build-server --node

# Add deploy targets (app servers)
python3 setup_server_web.py build.example.com --build-server \
  --deploy-target app1.example.com \
  --deploy example.com https://github.com/user/site.git
```

### App Server Setup

```bash
# Lightweight app server - nginx only, receives deployments from build server
python3 setup_server_web.py app1.example.com --app-server

# App server with SSL support
python3 setup_server_web.py app1.example.com --app-server --ssl --ssl-email admin@example.com
```

## Implementation

### Configuration Fields (`lib/config.py`)

```python
is_build_server: bool = False      # Configure as build server
is_app_server: bool = False        # Configure as app server
deploy_targets: Optional[StrList]  # List of app server hosts
```

### CLI Arguments (`lib/arg_parser.py`)

- `--build-server`: Configure as build server with CI/CD and deploy tools
- `--app-server`: Configure as lightweight app server
- `--deploy-target HOST`: Add app server as deployment target

### New Modules

| Module | Purpose |
|--------|---------|
| `web/app_server_steps.py` | App server setup (deploy user, sudoers, nginx) |
| `web/build_server_steps.py` | Build server setup (SSH keys, deploy targets) |
| `lib/remote_deploy.py` | Remote deployment utilities (rsync, SSH, nginx) |

### System Types

Build servers and app servers integrate with the existing system type infrastructure in `lib/system_types.py`. When `is_build_server` or `is_app_server` is set, the appropriate setup steps are automatically included.

## Architecture

### Build Server

```
┌─────────────────────────────────────────────────────────────┐
│                      BUILD SERVER                           │
├─────────────────────────────────────────────────────────────┤
│  webhook-receiver.service                                   │
│  cicd-executor.service                                      │
│                                                             │
│  /var/lib/infra_tools/cicd/                                │
│  ├── workspaces/           # Git clones + builds           │
│  ├── jobs/                 # Job queue                      │
│  ├── logs/                 # Build logs                     │
│  └── .ssh/deploy_key       # SSH key for app servers       │
│                                                             │
│  /etc/infra_tools/cicd/                                    │
│  ├── webhook_config.json   # Repository configurations     │
│  └── deploy_targets.json   # App server targets            │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ SSH/rsync
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       APP SERVER                            │
├─────────────────────────────────────────────────────────────┤
│  nginx                                                      │
│                                                             │
│  /var/www/                 # Deployed sites                 │
│  /etc/nginx/sites-available/  # Site configs from builder  │
│                                                             │
│  deploy user               # Restricted SSH access          │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Flow

1. **Webhook received** → webhook-receiver validates and queues job
2. **Job processed** → cicd-executor:
   - Clones/updates repository with `git clean -fdx && git reset --hard`
   - Runs install/build/test scripts
   - Detects project type and generates nginx config
   - Pushes artifacts via rsync to app server
   - Pushes nginx config to app server
   - Triggers nginx reload on app server

## Webhook Configuration

The webhook config now supports a `deploy_target` field:

```json
{
  "repositories": [
    {
      "url": "https://github.com/user/repo.git",
      "branches": ["main"],
      "deploy_target": "app1.example.com",
      "deploy_spec": "example.com/",
      "scripts": {
        "install": "npm ci",
        "build": "npm run build",
        "test": "npm test"
      }
    }
  ]
}
```

When `deploy_target` is specified, the build server pushes artifacts to that target instead of deploying locally.

## Security

### SSH Key Management

- Build server generates dedicated deploy key during setup
- Public key must be added to app server's `/home/deploy/.ssh/authorized_keys`
- SSH access uses `BatchMode=yes` for non-interactive operation

### App Server deploy User

The deploy user has restricted sudo access:

```
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart rails-*
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart node-*
```

## Example Workflow

### Initial Setup

```bash
# 1. Set up app server
python3 setup_server_web.py app1.example.com --app-server --cloudflare

# 2. Set up build server with deploy target
python3 setup_server_web.py build.example.com --build-server \
  --node --cloudflare \
  --deploy-target app1.example.com

# 3. Add build server's deploy key to app server
ssh app1.example.com
sudo cat /home/deploy/.ssh/authorized_keys  # Add build server's public key

# 4. Configure repository on build server
ssh build.example.com
sudo webhook-manager add https://github.com/user/site.git \
  --branches main \
  --build "npm run build" \
  --deploy-target app1.example.com
```

### Deployment (Automatic)

1. Developer pushes to GitHub
2. GitHub sends webhook to build server
3. Build server:
   - Clones repo with clean working directory
   - Runs `npm install && npm run build`
   - Generates nginx config for domain
   - rsync's `dist/` to `app1:/var/www/site/`
   - Pushes nginx config to `app1:/etc/nginx/sites-available/site`
   - Runs `ssh app1 'sudo systemctl reload nginx'`

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `web/app_server_steps.py` | App server setup steps |
| `web/build_server_steps.py` | Build server setup steps |
| `lib/remote_deploy.py` | Remote deployment utilities |
| `docs/BUILD_SERVER_DESIGN.md` | This documentation |

### Modified Files

| File | Changes |
|------|---------|
| `lib/config.py` | Added `is_build_server`, `is_app_server`, `deploy_targets` |
| `lib/arg_parser.py` | Added `--build-server`, `--app-server`, `--deploy-target` |
| `lib/system_types.py` | Added step lists and imports for build/app server |
| `web/steps.py` | Exported new step functions |
| `web/cicd_steps.py` | Fixed secret handling (EnvironmentFile), added env file support |
| `web/service_tools/cicd_executor.py` | Added lock file, git clean, remote deployment |
| `web/service_tools/webhook_receiver.py` | Fixed job filename collision |
| `web/service_tools/webhook_manager.py` | Fixed root check consistency |
| `tests/test_cicd.py` | Updated tests for new functionality |

## CI/CD Fixes Applied

1. **Security**: Webhook secret now uses `EnvironmentFile=` instead of embedding in systemd unit
2. **Concurrency**: Added lock file to prevent concurrent executor runs
3. **Job naming**: Uses timestamp + repo name + full SHA for unique job files
4. **Clean builds**: Added `git clean -fdx && git reset --hard` before checkout
5. **Permissions**: Fixed inconsistent root check in webhook-manager

## Testing

All 564 tests pass, including 23 new tests for:
- App server setup steps
- Build server setup steps
- Remote deployment utilities
