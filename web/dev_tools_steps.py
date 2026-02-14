"""Development tools auto-update steps for web servers."""

from __future__ import annotations

import os
import shlex
from typing import Optional

from lib.config import SetupConfig
from lib.remote_utils import run, is_service_active
from lib.systemd_service import cleanup_service


def _configure_auto_update_systemd(
    service_name: str,
    service_desc: str,
    timer_desc: str,
    script_name: str,
    schedule: str,
    check_path: str,
    check_name: str,
    user: Optional[str] = None
) -> None:
    """Helper to configure systemd service and timer for auto-updates."""
    if not os.path.exists(check_path):
        print(f"  ℹ {check_name} not installed, skipping auto-update configuration")
        return

    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"

    # Clean up any existing service/timer before creating new ones
    cleanup_service(service_name)

    script_path = f"/opt/infra_tools/web/service_tools/{script_name}"
    
    user_line = f"User={user}\n" if user else ""
    
    service_content = f"""[Unit]
Description={service_desc}
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
{user_line}ExecStart=/usr/bin/python3 {script_path}
StandardOutput=journal
StandardError=journal
"""

    with open(service_file, "w") as f:
        f.write(service_content)

    timer_content = f"""[Unit]
Description={timer_desc}
Documentation=man:systemd.timer(5)

[Timer]
OnCalendar={schedule}
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
"""

    with open(timer_file, "w") as f:
        f.write(timer_content)

    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}.timer")
    run(f"systemctl start {service_name}.timer")

    print(f"  ✓ {check_name} auto-update configured ({schedule})")


def configure_auto_update_node(config: SetupConfig) -> None:
    """Configure automatic updates for Node.js via nvm."""
    user_home = f"/home/{config.username}"
    nvm_dir = f"{user_home}/.nvm"
    
    _configure_auto_update_systemd(
        service_name="auto-update-node",
        service_desc="Auto-update Node.js to latest LTS",
        timer_desc="Auto-update Node.js weekly",
        script_name="auto_update_node.py",
        schedule="Sun *-*-* 03:00:00",
        check_path=nvm_dir,
        check_name="Node.js",
        user=config.username
    )


def configure_auto_update_ruby(config: SetupConfig) -> None:
    """Configure automatic updates for Ruby via rbenv."""
    user_home = f"/home/{config.username}"
    rbenv_dir = f"{user_home}/.rbenv"
    
    _configure_auto_update_systemd(
        service_name="auto-update-ruby",
        service_desc="Auto-update Ruby to latest stable version",
        timer_desc="Auto-update Ruby weekly",
        script_name="auto_update_ruby.py",
        schedule="Sun *-*-* 04:00:00",
        check_path=rbenv_dir,
        check_name="Ruby",
        user=config.username
    )
