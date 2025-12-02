# infra_tools

Infrastructure management tools for remote workstation setup.

## setup_workstation_desktop.py

A Python script that sets up a remote Linux workstation for RDP access.

### Files

- `setup_workstation_desktop.py` - Local script that transfers and runs the remote setup
- `remote_setup.py` - Setup script that runs on the target host (can also be run directly)

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
- **Idempotent**: Safe to run multiple times to propagate updates

### Requirements

- Python 3.9+ (on local machine)
- Python 3 on the remote host
- SSH key-based access to the remote host as root
- Supported remote OS: Debian, Ubuntu, or Fedora (modern RHEL-based)

### Usage

```bash
# Basic usage (creates user with auto-generated password)
python3 setup_workstation_desktop.py [IP address] [username]

# With custom password
python3 setup_workstation_desktop.py [IP address] [username] -p "password"

# Without setting password (for existing users)
python3 setup_workstation_desktop.py [IP address] [username] --no-password

# With specific timezone
python3 setup_workstation_desktop.py [IP address] [username] -t "America/New_York"
```

### Examples

Basic usage (generates a random password):
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

Configure existing user without changing password:
```bash
python3 setup_workstation_desktop.py 192.168.1.100 johndoe --no-password
```

### Running Directly on Host

The `remote_setup.py` script can also be run directly on the target machine:

```bash
# Set up current user
python3 remote_setup.py

# Set up specific user (creates if needed)
python3 remote_setup.py johndoe

# Set up user with password
python3 remote_setup.py johndoe "mypassword"

# Set up user with password and timezone
python3 remote_setup.py johndoe "mypassword" "America/New_York"
```

### Options

| Option | Description |
|--------|-------------|
| `ip` | IP address of the remote host |
| `username` | Username for the sudo-enabled user |
| `-k, --key` | Path to SSH private key (optional) |
| `-p, --password` | Password for the user (optional, auto-generated if not specified) |
| `--no-password` | Don't set/change password (useful for existing users) |
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

4. **Password Generation**: When no password is specified, generates a 16-character
   cryptographically secure random password.

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

1. The local script reads `remote_setup.py` and transfers it via SSH
2. Output is streamed in real-time during execution
3. The remote script runs on the target host with username, password, and timezone
4. OS detection happens on the remote host
5. UTF-8 locale is configured to ensure proper terminal support
6. All configuration is performed in a single SSH session

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

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
