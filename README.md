# infra_tools

Infrastructure management tools for remote system setup.

## Overview

This repository provides automated setup scripts for remote Linux systems with two main configurations:

- **Workstation Desktop** (`setup_workstation_desktop.py`): Full desktop environment with RDP access
- **Server Dev** (`setup_server_dev.py`): Lightweight development server without desktop/RDP

### Files

- `setup_workstation_desktop.py` - Local script for workstation desktop setup
- `setup_server_dev.py` - Local script for development server setup
- `setup_common.py` - Shared functionality between setup scripts
- `remote_setup.py` - Remote setup script that runs on the target host (can also be run directly)
- `remote_modules/` - Modular components for the remote setup:
  - `utils.py` - Utility functions (validation, OS detection, package checks)
  - `progress.py` - Progress tracking with visual progress bar
  - `steps.py` - Individual setup step functions with idempotency checks

## setup_workstation_desktop.py

A Python script that sets up a remote Linux workstation for RDP access.

### Features

- Creates a new sudo-enabled user or configures an existing one
- Installs XFCE desktop environment (lightweight)
- Installs and configures xRDP for remote desktop access
- Configures audio for RDP (PulseAudio + xRDP module)
- Applies secure defaults:
  - Firewall configuration (UFW/firewalld)
  - SSH hardening (disables root password login, password authentication)
  - fail2ban protection for RDP (3 failed attempts = 1 hour ban)
- Configures NTP time synchronization (uses local machine's timezone by default)
- Enables automatic security updates
- Configures UTF-8 locale (fixes btop and other tools)
- Installs CLI tools: neovim, btop, htop, curl, wget, git, tmux, unzip
- Installs desktop apps via native packages: LibreOffice, Brave, VSCodium, Discord
- Sets Brave as the default web browser
- **Idempotent**: Safe to run multiple times; skips already-completed steps
- **Progress Tracking**: Visual progress bar shows completion status

### Requirements

- Python 3.9+ (on local machine)
- Python 3 on the remote host
- SSH key-based access to the remote host as root
- Supported remote OS: Debian, Ubuntu, or Fedora (modern RHEL-based)

### Usage

```bash
# Basic usage (uses current username)
python3 setup_workstation_desktop.py [IP address]

# With specific username
python3 setup_workstation_desktop.py [IP address] [username]

# With custom password (sets password for new or existing user)
python3 setup_workstation_desktop.py [IP address] [username] -p "password"

# With specific timezone
python3 setup_workstation_desktop.py [IP address] [username] -t "America/New_York"
```

### Examples

Basic usage (uses current username, generates password only if creating new user):
```bash
python3 setup_workstation_desktop.py 192.168.1.100
```

With specific username:
```bash
python3 setup_workstation_desktop.py 192.168.1.100 johndoe
```

With a specific SSH key:
```bash
python3 setup_workstation_desktop.py 192.168.1.100 johndoe -k ~/.ssh/my_key
```

With a custom password:
```bash
python3 setup_workstation_desktop.py 192.168.1.100 johndoe -p "MySecurePassword123!"
```

### Running Directly on Host

The `remote_setup.py` script can also be run directly on the target machine. After
the first remote setup, scripts are installed at `/opt/infra_tools/`:

```bash
# Workstation desktop setup with current user (generates password)
python3 /opt/infra_tools/remote_setup.py workstation_desktop

# Workstation desktop setup with specific user (creates if needed, generates password)
python3 /opt/infra_tools/remote_setup.py workstation_desktop johndoe

# Workstation desktop setup with user and password
python3 /opt/infra_tools/remote_setup.py workstation_desktop johndoe "mypassword"

# Workstation desktop setup with user, password and timezone
python3 /opt/infra_tools/remote_setup.py workstation_desktop johndoe "mypassword" "America/New_York"

# For backward compatibility (defaults to workstation_desktop):
python3 /opt/infra_tools/remote_setup.py johndoe "mypassword" "America/New_York"
```

### Options

| Option | Description |
|--------|-------------|
| `ip` | IP address of the remote host |
| `username` | Username for the sudo-enabled user (defaults to current user) |
| `-k, --key` | Path to SSH private key (optional) |
| `-p, --password` | Password for the user (only used when creating new user or updating existing) |
| `-t, --timezone` | Timezone for remote host (defaults to local machine's timezone) |

### Security

The script applies the following security measures:

1. **Firewall**: Configures UFW (Debian/Ubuntu) or firewalld (Fedora) to:
   - Default deny incoming connections
   - Allow SSH (port 22)
   - Allow RDP (port 3389)

2. **RDP Brute-Force Protection**: Configures fail2ban to:
   - Monitor xRDP login attempts
   - Ban IPs after 3 failed attempts
   - Ban duration: 1 hour
   - Detection window: 10 minutes

3. **SSH Hardening**:
   - Creates a backup of the original SSH config (`/etc/ssh/sshd_config.bak`)
   - Disables root password login (`PermitRootLogin prohibit-password`)
   - Disables password authentication for SSH (`PasswordAuthentication no`)
   - Disables X11 forwarding
   - Limits authentication attempts to 3

4. **Password Generation**: When creating a new user without specifying a password,
   generates a 16-character cryptographically secure random password.

5. **SSH Host Key Handling**: Uses `accept-new` policy which accepts new host keys
   but rejects changed keys. For maximum security, verify the host key fingerprint
   manually before running this script in sensitive environments.

6. **Automatic Updates**: Enables automatic security updates:
   - Debian/Ubuntu: unattended-upgrades (daily security updates)
   - Fedora: dnf-automatic (security updates only)

7. **Time Synchronization**: Configures NTP via systemd-timesyncd (Debian) or
   chrony (Fedora). Uses the local machine's timezone by default.

### Pre-installed Software

**CLI Tools** (installed via system package manager):
- sudo - Privilege escalation (for minimal distros)
- neovim - Modern text editor
- btop - Resource monitor
- htop - Interactive process viewer
- curl, wget - HTTP clients
- git - Version control
- tmux - Terminal multiplexer
- unzip - Archive utility

**Desktop Applications** (installed via native packages/official repos):
- LibreOffice - Office suite
- Brave - Privacy-focused web browser (set as default)
- VSCodium - Open-source code editor
- Discord - Communication platform (Debian only)

### How It Works

1. The local script creates a tar archive of `remote_setup.py` and `remote_modules/`
2. The archive is transferred via SSH and extracted to `/opt/infra_tools/` on the remote host
3. The remote script runs with username, password, and timezone arguments
4. OS detection happens on the remote host
5. UTF-8 locale is configured to ensure proper terminal support
6. All configuration is performed in a single SSH session
7. The scripts remain installed at `/opt/infra_tools/` for future use

### After Setup

1. Connect using an RDP client (e.g., Remmina, Microsoft Remote Desktop)
2. Use the IP address and port 3389
3. Login with the created username and password
4. Consider changing the password after first login

### Audio Configuration

Audio is configured using PulseAudio with the xRDP sound module. For Remmina:
1. In connection settings, set "Audio output mode" to "Local"
2. Audio should work automatically in the RDP session

Note: In unprivileged containers (e.g., Proxmox LXC), audio may require the 
pulseaudio-module-xrdp package to be built from source on Debian systems.

## setup_server_dev.py

A Python script that sets up a remote Linux server for development without desktop/RDP.

### Features

- Creates a new sudo-enabled user or configures an existing one
- Applies secure defaults:
  - Firewall configuration (UFW/firewalld)
  - SSH hardening (disables root password login, password authentication)
- Configures NTP time synchronization (uses local machine's timezone by default)
- Enables automatic security updates
- Configures UTF-8 locale (fixes btop and other tools)
- Installs CLI tools: neovim, btop, htop, curl, wget, git, tmux, unzip
- **No desktop environment**: Lightweight server configuration
- **No RDP**: Direct SSH access only
- **No audio or desktop applications**: Focus on development tools
- **Idempotent**: Safe to run multiple times; skips already-completed steps
- **Progress Tracking**: Visual progress bar shows completion status

### Requirements

- Python 3.9+ (on local machine)
- Python 3 on the remote host
- SSH key-based access to the remote host as root
- Supported remote OS: Debian, Ubuntu, or Fedora (modern RHEL-based)

### Usage

```bash
# Basic usage (uses current username)
python3 setup_server_dev.py [IP address]

# With specific username
python3 setup_server_dev.py [IP address] [username]

# With custom password
python3 setup_server_dev.py [IP address] [username] -p "password"

# With specific timezone
python3 setup_server_dev.py [IP address] [username] -t "America/New_York"
```

### Examples

Basic usage (uses current username, generates password only if creating new user):
```bash
python3 setup_server_dev.py 192.168.1.100
```

With specific username:
```bash
python3 setup_server_dev.py 192.168.1.100 johndoe
```

With a specific SSH key:
```bash
python3 setup_server_dev.py 192.168.1.100 johndoe -k ~/.ssh/my_key
```

With a custom password:
```bash
python3 setup_server_dev.py 192.168.1.100 johndoe -p "MySecurePassword123!"
```

### Running Directly on Host

The `remote_setup.py` script can also be run directly on the target machine:

```bash
# Server dev setup with current user (generates password)
python3 /opt/infra_tools/remote_setup.py server_dev

# Server dev setup with specific user (creates if needed, generates password)
python3 /opt/infra_tools/remote_setup.py server_dev johndoe

# Server dev setup with user and password
python3 /opt/infra_tools/remote_setup.py server_dev johndoe "mypassword"

# Server dev setup with user, password and timezone
python3 /opt/infra_tools/remote_setup.py server_dev johndoe "mypassword" "America/New_York"
```

### Options

| Option | Description |
|--------|-------------|
| `ip` | IP address of the remote host |
| `username` | Username for the sudo-enabled user (defaults to current user) |
| `-k, --key` | Path to SSH private key (optional) |
| `-p, --password` | Password for the user (only used when creating new user or updating existing) |
| `-t, --timezone` | Timezone for remote host (defaults to local machine's timezone) |

### After Setup

1. Connect via SSH:
   ```bash
   ssh [username]@[IP address]
   ```
2. Consider changing the password after first login

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
