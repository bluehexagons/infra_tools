"""Development tools auto-update steps for web servers."""

from __future__ import annotations

from common.common_steps import configure_auto_update_ruby as _configure_auto_update_ruby_common
from lib.maintenance_systemd import configure_maintenance_timer
from lib.config import SetupConfig
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV


def configure_auto_update_node(config: SetupConfig) -> None:
    """Configure automatic updates for Node.js via nvm."""
    user_home = f"/home/{config.username}"
    nvm_dir = f"{user_home}/.nvm"
    
    configure_maintenance_timer(
        service_name="auto-update-node",
        service_desc="Auto-update Node.js via nvm",
        timer_desc="Auto-update Node.js weekly",
        script_path="/opt/infra_tools/web/service_tools/auto_update_node.py",
        schedule="Sun *-*-* 03:00:00",
        check_path=f"{nvm_dir}/nvm.sh",
        check_name="Node.js",
        user=config.username,
        environment={ECOSYSTEM_AUTO_UPGRADE_ENV: "0"},
        purpose="auto-update",
    )


def configure_auto_update_ruby(config: SetupConfig) -> None:
    """Configure automatic updates for Ruby via apt packages."""
    _configure_auto_update_ruby_common(config)
