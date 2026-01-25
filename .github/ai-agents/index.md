# AI Agent Documentation Index

📁 **Quick navigation for AI agents working on infra_tools**

## 📖 Essential Reading (2 minutes)

### [README.md](./README.md) ⭐ **Start here**
Core instructions, workflow, machine type awareness, directory structure

### [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) 📋 **Reference**  
Type aliases, machine state helpers, function templates, module organization

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

**Start with `README.md`** - workflow, patterns, and machine type awareness.

## 🔧 Need More Detail?

- **Type usage**: See `QUICK_REFERENCE.md` for `JSONDict`, `StrList`, etc.
- **Machine state**: See `QUICK_REFERENCE.md` for capability helpers
- **Project structure**: Module organization in both files
- **Testing**: Compile check and dry-run commands

---

**Remember: Read the target file completely before making changes, check machine type capabilities for system-level operations, and always test with `python3 -m py_compile`**