# Module Structure Migration Guide

## Overview

The infra_tools repository has been reorganized from a type-based structure to a module-based (functionality-based) structure to improve maintainability and make it easier to understand what code relates to which functionality.

## New Module Structure

### Module Organization

Each module contains:
- `steps.py` - Step functions for that module's functionality
- `service_tools/` - Scripts that run as services or background tasks (optional)
- `config/` - Configuration files and templates (optional)
- `__init__.py` - Module initialization

### Available Modules

1. **lib/** - Core shared libraries
   - Configuration, types, utilities
   - Import helpers and system utils
   - Should not be directly modified when adding new features

2. **common/** - Common setup steps
   - User and package management
   - Locale and timezone configuration
   - Ruby, Node, Go installation
   - CLI tools
   - `service_tools/`: auto_update_node.py, auto_update_ruby.py, auto_restart_if_needed.py

3. **desktop/** - Desktop/workstation functionality
   - Desktop environments (XFCE, i3, Cinnamon)
   - xRDP remote desktop
   - Audio configuration
   - Desktop applications and browsers
   - `config/`: xRDP templates
   - `service_tools/`: xrdp_session_cleanup.py

4. **web/** - Web server functionality
   - Nginx installation and configuration
   - Site setup and security
   - `config/`: Nginx templates, Cloudflare config
   - `service_tools/`: setup_cloudflare_tunnel.py

5. **security/** - Security hardening
   - Firewall configuration
   - SSH hardening
   - Kernel hardening
   - fail2ban
   - Auto-updates

6. **smb/** - SMB/Samba functionality
   - Samba server setup
   - SMB client mounting

7. **sync/** - Sync and data integrity
   - rsync synchronization
   - par2 data verification
   - `service_tools/`: scrub_par2.py, check_sync_mounts.py, check_scrub_mounts.py

8. **deploy/** - Application deployment
   - Rails, Node/Vite, static site deployment
   - `service_tools/`: setup_rails_service.py

## How to Add New Functionality

### Adding a New Step to an Existing Module

1. Add your step function to the appropriate module's `steps.py`:
   ```python
   # In desktop/steps.py
   def install_new_desktop_app(config: SetupConfig) -> None:
       """Install a new desktop application."""
       # Your implementation here
       pass
   ```

2. Export it from the module's `steps.py`:
   ```python
   __all__ = [
       # ... existing exports
       'install_new_desktop_app',
   ]
   ```

3. If the step also needs to be callable from lib, add it to `lib/desktop_steps.py` or import it there.

4. Register it in `lib/system_types.py` if it should be part of a system type:
   ```python
   from desktop.steps import install_new_desktop_app
   
   # Add to STEP_FUNCTIONS dict
   STEP_FUNCTIONS['install_new_desktop_app'] = install_new_desktop_app
   ```

### Adding a New Module

1. Create the module directory structure:
   ```bash
   mkdir -p mymodule/service_tools mymodule/config
   ```

2. Create `mymodule/__init__.py`:
   ```python
   """My module for infra_tools."""
   ```

3. Create `mymodule/steps.py`:
   ```python
   """My module setup steps."""
   
   from __future__ import annotations
   import sys
   import os
   sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
   
   from lib.config import SetupConfig
   from lib.remote_utils import run
   
   def my_step(config: SetupConfig) -> None:
       """Do something useful."""
       run("echo 'Hello from my module'")
       print("  ✓ My step completed")
   
   __all__ = ['my_step']
   ```

4. Add to `lib/setup_common.py` in the `copy_project_files` function:
   ```python
   items_to_copy = ["remote_setup.py", "lib", "desktop", "web", "smb", 
                    "security", "sync", "common", "deploy", "mymodule"]
   ```

5. Import and register in `lib/system_types.py`:
   ```python
   from mymodule.steps import my_step
   
   STEP_FUNCTIONS['my_step'] = my_step
   ```

### Adding Service Tools

Service tools are scripts that run as systemd services or are called by services.

1. Create your script in the appropriate module's `service_tools/` directory:
   ```bash
   touch mymodule/service_tools/my_service.py
   chmod +x mymodule/service_tools/my_service.py
   ```

2. Add the shebang and make it executable:
   ```python
   #!/usr/bin/env python3
   """My service script."""
   
   import sys
   # Your service logic here
   ```

3. Reference it from your step function using the module path:
   ```python
   def setup_my_service(config: SetupConfig) -> None:
       script_path = "/opt/infra_tools/mymodule/service_tools/my_service.py"
       # Create systemd service, etc.
   ```

### Adding Configuration Templates

1. Add templates to the module's `config/` directory:
   ```bash
   echo "# My template" > mymodule/config/my_template.conf
   ```

2. Reference them in your steps:
   ```python
   def configure_my_service(config: SetupConfig) -> None:
       config_dir = os.path.join(os.path.dirname(__file__), 'config')
       template_path = os.path.join(config_dir, 'my_template.conf')
       with open(template_path, 'r') as f:
           template = f.read()
       # Use the template
   ```

## Importing from Modules

### Static Imports (Recommended)

Import directly from module files:
```python
from desktop.steps import install_desktop, install_xrdp
from web.steps import install_nginx
from common.steps import update_and_upgrade_packages
```

### Dynamic Imports

Use the module loader for dynamic discovery:
```python
from lib.module_loader import get_module_steps, import_from_module

# Get all functions from a module
desktop_steps = get_module_steps('desktop')

# Import specific items
items = import_from_module('web.steps', 'install_nginx', 'configure_nginx_security')
```

## Migration from Old Structure

### Old → New Mapping

| Old Location | New Location |
|-------------|--------------|
| `config/nginx*.conf` | `web/config/` |
| `config/xrdp*.template` | `desktop/config/` |
| `config/cloudflare*` | `web/config/` |
| `service_tools/auto_update_*.py` | `common/service_tools/` |
| `service_tools/auto_restart_*.py` | `common/service_tools/` |
| `service_tools/scrub_par2.py` | `sync/service_tools/` |
| `service_tools/setup_cloudflare_tunnel.py` | `web/service_tools/` |
| `steps/check_*_mounts.py` | `sync/service_tools/` |
| `steps/setup_rails_service.py` | `deploy/service_tools/` |
| `steps/xrdp_session_cleanup.py` | `desktop/service_tools/` |
| `lib/desktop_steps.py` | Still exists; also in `desktop/steps.py` |
| `lib/web_steps.py` | Still exists; also in `web/steps.py` |
| `lib/security_steps.py` | Still exists; also in `security/steps.py` |

### Backward Compatibility

The old `lib/*_steps.py` files still exist and work. The new module structure imports and wraps these for now. This allows for a gradual migration where:

1. Old code can continue importing from `lib.desktop_steps`
2. New code should import from `desktop.steps`
3. Both reference the same underlying functions

## Benefits of the New Structure

1. **Better Organization**: Related code is grouped together by functionality
2. **Easier Navigation**: Find all desktop-related code in one module
3. **Clearer Responsibilities**: Each module has a clear purpose
4. **Scalability**: Easy to add new modules without cluttering the lib directory
5. **Service Tools Co-location**: Scripts are next to the steps that use them
6. **Config Templates Co-location**: Templates are next to the steps that use them

## Testing Your Changes

After making changes:

1. Test imports work:
   ```bash
   python3 -c "from mymodule.steps import my_step; print('✓ Import works')"
   ```

2. Test step loading:
   ```bash
   python3 -c "from lib.system_types import STEP_FUNCTIONS; print(STEP_FUNCTIONS['my_step'])"
   ```

3. Test dry-run:
   ```bash
   python3 setup_*.py localhost --dry-run
   ```

## Questions?

See the main README.md for the complete repository structure and setup script documentation.
