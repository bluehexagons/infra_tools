# AI Agent Documentation Index

📁 **Quick navigation for AI agents working on infra_tools**

## 📖 Essential Reading (2 minutes)

### [README.md](./README.md) ⭐ **Start here**
Core instructions, workflow, machine type awareness, testing guidelines, known challenges

### [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) 📋 **Reference**  
Type aliases, machine state helpers, function templates, module organization, testing rules

## 🎯 What This Project Does

Automates Linux server/workstation setup via SSH with:
- Security hardening (SSH, firewall, fail2ban, kernel)
- Desktop environments (XRDP, audio, browsers, apps)
- Application deployment (Rails, Node.js, static sites)
- Service management (systemd, nginx, SSL, Cloudflare)
- Data management (Samba, rsync sync, par2 integrity)
- Environment adaptation (LXC, VM, bare metal, OCI containers)

## 🖥️ Machine Type Support

Setup adapts to environment capabilities:
- **unprivileged** (LXC) - Default, limited kernel access
- **vm** - Full virtualization
- **privileged** - LXC with GPU/hardware passthrough
- **hardware** - Bare metal
- **oci** - Docker/Podman (most limited)

See `docs/MACHINE_TYPES.md` for capability matrix.

## ⚡ If You Only Read One Thing

**Start with `README.md`** - workflow, patterns, testing, and machine type awareness.

## 🔧 Need More Detail?

- **Type usage**: See `QUICK_REFERENCE.md` for `JSONDict`, `StrList`, etc.
- **Machine state**: See `QUICK_REFERENCE.md` for capability helpers
- **Project structure**: Module organization in both files
- **Testing**: Testing guidelines and known challenges in `README.md`
- **Storage systems**: See `docs/STORAGE.md` for NAS/backup architecture
- **Logging**: See `docs/LOGGING.md` for centralized logging

## 📝 Keeping Docs Up to Date

When making changes to the codebase:
- Update relevant `docs/*.md` files if architecture or usage changes
- Update these agent instruction files if coding patterns or conventions change
- Document specific problems or challenges encountered for future reference
- Remove deprecated content rather than marking it as "kept for compatibility"

---

**Remember: Read the target file completely before making changes, check machine type capabilities for system-level operations, run tests with `python3 -m pytest tests/ -v`, and keep docs up to date.**