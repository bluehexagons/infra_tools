# Copilot Instructions

## Project Overview

This repository contains automated setup scripts for remote Linux systems (Debian-based). The scripts automate server provisioning, workstation configuration, and deployment of web applications with security hardening, firewall configuration, and service management.

**Target Users:** System administrators, DevOps engineers, and developers managing remote Linux infrastructure.

## Technology Stack

- **Language:** Python 3.9+
- **Target OS:** Debian-based Linux distributions
- **Remote Access:** SSH (Paramiko library)
- **Configuration Management:** Python scripts with modular design
- **Services:** Nginx, Systemd, UFW firewall, Chrony, Samba
- **Deployment Support:** Ruby/Rails, Node.js/Vite, static sites

## Repository Setup

The scripts use Python's standard library and require only SSH access to target systems. No local dependencies are required beyond Python 3.9+.

**Local Setup:**
```bash
# No installation needed - scripts are self-contained
# Ensure Python 3.9+ is installed
python3 --version

# Run a setup script (example)
python3 setup_server_web.py example.com --ruby --node
```

**Remote System Requirements:**
- Debian-based Linux (target)
- SSH root access or sudo user
- Internet connectivity

## Directory Structure

- `/lib` - Core library modules (arg parsing, config, validators, setup utilities)
- `/shared` - Shared utilities for deployment and service management
- `/remote_modules` - Modules executed on remote systems
- `setup_*.py` - Main setup scripts for different system types
- `patch_setup.py` - Update existing systems or manage saved configurations
- `remote_setup.py` - Script executed on remote systems

## Core Guidelines

### Backwards Compatibility
- Backwards compatibility is never required
- Simplify code without concern for legacy support
- Remove deprecated patterns and old workarounds

### Code Quality
- Don't repeat yourself (DRY principle)
- Extract common functionality into shared modules
- Use composition over duplication
- Use type hints for function parameters and return values
- Follow Python conventions (PEP 8 style)

### Code Style
- Use 4-space indentation (Python standard)
- Type hints required for all function signatures
- Use dataclasses for configuration objects (see `lib/config.py`)
- Import standard library first, then third-party, then local modules
- Functions should have descriptive names using snake_case

### Documentation
- Only use comments for important documentation
- Code should be self-explanatory through clear naming
- Avoid obvious or redundant comments
- Document security-sensitive operations
- Include docstrings for complex functions

### README
- Keep README concise and focused
- Include only essential usage and features
- Avoid verbose explanations

## Security Considerations

- All scripts apply security hardening (SSH, firewall, fail2ban)
- Use key-based authentication for SSH when possible
- Default-deny firewall rules with UFW
- Validate user inputs (see `lib/validators.py`)
- Never commit secrets or credentials to the repository
- Review `SECURITY.md` for detailed security measures
