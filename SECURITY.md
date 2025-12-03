# Security

This document outlines the security measures implemented by the setup scripts and provides recommendations for additional hardening.

## Implemented Security Measures

### Network Security
- **Firewall**: UFW (Debian/Ubuntu) or firewalld (Fedora) with default-deny incoming
- **SSH Hardening**:
  - Key-only authentication (password auth disabled)
  - Root login requires keys (no passwords)
  - Max 3 authentication attempts
  - Client timeouts (300s idle, 2 retries)
  - Protocol 2 only
  - No empty passwords allowed
  - X11 forwarding disabled
- **fail2ban** (desktop systems): RDP brute-force protection (3 attempts = 1 hour ban)
- **Kernel Network Hardening**:
  - SYN cookies enabled (DDoS protection)
  - ICMP redirects disabled
  - Reverse path filtering enabled
  - Martian packet logging
  - Broadcast echo ignore

### System Security
- **Automatic Updates**: Daily security updates via unattended-upgrades (Debian) or dnf-automatic (Fedora)
- **Package Management**: System updated and upgraded before setup
- **User Management**:
  - Non-root user with sudo privileges
  - SSH keys automatically copied from root
  - Strong 16-character passwords generated when not provided
- **Kernel Hardening**:
  - dmesg restricted
  - Kernel pointer hiding
  - ptrace scope limited
  - No SUID core dumps

### Monitoring
- Restart detection after kernel/system updates

## Recommendations for Internet-Facing Servers

### High Priority
1. **SSH Access**: Use VPN or bastion host instead of direct SSH exposure
2. **Non-Standard Ports**: Consider moving SSH to non-standard port
3. **IP Whitelisting**: Restrict SSH to known IPs if possible
4. **Process Limits**: Configure ulimits to prevent resource exhaustion

### For Web Servers
1. **HTTPS Only**: Use Let's Encrypt for free SSL/TLS certificates
2. **WAF**: Install ModSecurity or similar Web Application Firewall
3. **HTTP Security Headers**:
   - Enable HSTS (HTTP Strict Transport Security)
   - Set Content-Security-Policy
   - Configure X-Frame-Options
   - Set X-Content-Type-Options
4. **Rate Limiting**: Implement nginx limit_req or similar
5. **fail2ban**: Add HTTP-specific jails for common attacks
6. **Hide Version**: Disable server version headers
7. **Directory Listing**: Ensure directory browsing is disabled

### Monitoring & Logging
1. **File Integrity**: Install AIDE or similar for file integrity monitoring
2. **Log Monitoring**: Configure centralized logging and alerts
3. **Intrusion Detection**: Consider OSSEC or similar IDS
4. **Failed Login Alerts**: Set up notifications for failed authentication

### Application Security
1. **SELinux/AppArmor**: Enable and configure MAC (Mandatory Access Control)
2. **Container Isolation**: Use containers for application isolation
3. **Least Privilege**: Run services with minimal permissions
4. **Regular Audits**: Perform security audits and penetration testing

## Secure Configuration Checklist

- [ ] Review and restrict sudo access
- [ ] Enable and configure SELinux/AppArmor
- [ ] Set up monitoring and alerting
- [ ] Configure backups
- [ ] Document incident response procedures
- [ ] Regular security update schedule
- [ ] Audit user accounts and access
- [ ] Review firewall rules
- [ ] Test disaster recovery procedures

## Reporting Security Issues

Security issues should be reported privately to the repository maintainers.
