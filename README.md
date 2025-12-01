# infra_tools

Infrastructure management tools for remote workstation setup.

## setup_workstation_desktop.py

A Python script that sets up a remote Linux workstation for RDP access.

### Files

- `setup_workstation_desktop.py` - Local script that transfers and runs the remote setup
- `remote_setup.py` - Setup script that runs on the target host

### Features

- Connects to a remote host via SSH using key-based authentication
- Creates a new sudo-enabled user
- Installs XFCE desktop environment (lightweight)
- Installs and configures xRDP for remote desktop access
- Applies secure defaults:
  - Firewall configuration (UFW/firewalld)
  - SSH hardening (disables root password login, password authentication)
  - fail2ban protection for RDP (3 failed attempts = 1 hour ban)
- Configures NTP time synchronization
- Enables automatic security updates

### Requirements

- Python 3.9+ (on local machine)
- Python 3 on the remote host
- SSH key-based access to the remote host as root
- Supported remote OS: Debian, Ubuntu, or Fedora (modern RHEL-based)

### Usage

```bash
python3 setup_workstation_desktop.py [IP address] [username]
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

### Options

| Option | Description |
|--------|-------------|
| `ip` | IP address of the remote host |
| `username` | Username for the new sudo-enabled user |
| `-k, --key` | Path to SSH private key (optional) |
| `-p, --password` | Password for the new user (optional, auto-generated if not specified) |

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
   chrony (Fedora) with UTC timezone as default.

### How It Works

1. The local script reads `remote_setup.py` and transfers it via SSH
2. The remote script runs on the target host with username and password as arguments
3. OS detection happens on the remote host
4. All configuration is performed in a single SSH session

### After Setup

1. Connect using an RDP client (e.g., Remmina, Microsoft Remote Desktop, Windows Remote Desktop)
2. Use the IP address and port 3389
3. Login with the created username and password
4. Consider changing the password after first login

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
