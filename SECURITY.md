# Security

This document explains the security measures the setup scripts apply, the defaults enabled during setup, and practical, actionable steps you can run after setup to harden a system further. Most of these recommendations are intended for production or Internet-facing servers.

## What the setup script configures by default
- Firewall rules (UFW-based)
  - Default-deny incoming, allows essential ports such as 22/80/443
- SSH hardening
  - Disallow root password logins; use key-based authentication
  - Limit authentication attempts and increase session timeouts
  - Disable X11-forwarding
- System-level hardening
  - Kernel network security settings (rp_filter, ICMP redirect off, etc.)
  - Restrict ptrace via kernel config
  - Restrict dmesg permissions and kernel pointers where possible
- Automatic security updates
  - unattended-upgrades is set to perform security updates
- Nginx security settings and default site hardening
  - Basic security headers and HSTS if TLS is enabled
  - Default site is static-only, no scripting executed by default
- swap configuration
  - If swap is absent, the script creates a safe-sized /swapfile based on system RAM and disk.

## Recommended server hardening actions for public-facing systems
- (High) Run the server behind a VPN or a bastion host, and whitelist SSH source IPs.
- (High) Enable 2FA for SSH if you need to keep password-based access for some users.
- Add `fail2ban` jails for HTTP endpoints and configure rate-limiting rules to protect against common brute force and DoS attempts.
  - Example: protect `/admin` paths or CMS endpoints specifically, and add a generic rule for too many requests.
- Use `ufw` with explicit policies for each service (e.g., only allow 22 from specific IPs, 443 from everyone, etc.).

## Secure system maintenance
- Use separate accounts for admin/service with specific SSH keys.
- Schedule automated security updates and verify them with a canary instance if you manage many servers.
- Execute regular security audits and use infrastructure-as-code with immutable patterns where possible.

## Reporting security issues
If you find a vulnerability, please report it privately to the repository maintainers using the contact in the project. Avoid disclosing details publicly until a mitigation is available.

---

This file focuses on practical, prioritized recommendations relevant to infra_tools and the environments this toolkit deploys to. It is not a substitute for regular professional security audits for production systems.