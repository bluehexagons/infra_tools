"""Service management framework building on systemd_service.py patterns."""

from __future__ import annotations
import os
import re
import secrets
import time
from typing import Optional, Any, Callable

from lib.config import SetupConfig
from lib.remote_utils import run
from lib.validation import validate_service_name_uniqueness



class ServiceManager:
    """Unified service management for backup and integrity operations."""
    
    def __init__(self, base_config: SetupConfig):
        """Initialize service manager.
        
        Args:
            base_config: Base setup configuration
        """
        self.config = base_config
        self.active_services: dict[str, dict[str, Any]] = {}
        self.service_templates: dict[str, Callable[[dict[str, Any]], str]] = {
            'backup': self._generate_backup_service_template,
            'scrub': self._generate_scrub_service_template,
            'sync': self._generate_sync_service_template,
        }
    
    def validate_service_uniqueness(self, service_name: str) -> bool:
        """Validate that service name doesn't conflict with existing services.
        
        Args:
            service_name: Service name to validate
            
        Returns:
            bool: True if service name is unique, False otherwise
        """
        # Get existing systemd services
        try:
            result = run("systemctl list-units --type=service --all", check=False, capture_output=True)
            if result.returncode == 0:
                existing_services: list[str] = []
                for line in result.stdout.split('\n'):
                    if '.service' in line:
                        service_match = re.search(r'([a-zA-Z0-9_-]+)\.service', line)
                        if service_match:
                            existing_services.append(service_match.group(1))
                
                try:
                    validate_service_name_uniqueness(service_name, existing_services)
                    return True
                except ValueError as e:
                    print(f"Service validation failed: {e}")
                    return False
        except Exception as e:
            print(f"Error checking existing services: {e}")
            return False
        
        return True
    
    def create_backup_service(self, service_config: dict[str, Any]) -> str:
        """Create a backup service.
        
        Args:
            service_config: Configuration dictionary for backup service
            
        Returns:
            str: Service name
        """
        service_name = service_config.get('name', f"backup-{secrets.token_hex(4)}")
        
        if not self.validate_service_uniqueness(service_name):
            raise ValueError(f"Service name '{service_name}' already exists or is invalid")
        
        service_content = self._generate_backup_service_template(service_config)
        service_file = f"/etc/systemd/system/{service_name}.service"
        
        # Ensure we have root permissions
        if os.geteuid() != 0:
            raise PermissionError("Creating systemd services requires root privileges")
        
        try:
            with open(service_file, 'w') as f:
                f.write(service_content)
        except IOError as e:
            raise IOError(f"Failed to write service file {service_file}: {e}")
        
        # Enable and start the service
        run("systemctl daemon-reload")
        run(f"systemctl enable {service_name}")
        run(f"systemctl restart {service_name}")
        
        # Verify service is running
        time.sleep(1)
        result = run(f"systemctl is-active {service_name}", check=False)
        if result.returncode != 0:
            print(f"Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
        else:
            print(f"✓ Created and started backup service: {service_name}")
        
        self.active_services[service_name] = {
            'type': 'backup',
            'config': service_config,
            'created_at': time.time()
        }
        
        return service_name
    
    def create_scrub_service(self, service_config: dict[str, Any]) -> str:
        """Create a scrub service.
        
        Args:
            service_config: Configuration dictionary for scrub service
            
        Returns:
            str: Service name
        """
        service_name = service_config.get('name', f"scrub-{secrets.token_hex(4)}")
        
        if not self.validate_service_uniqueness(service_name):
            raise ValueError(f"Service name '{service_name}' already exists or is invalid")
        
        service_content = self._generate_scrub_service_template(service_config)
        service_file = f"/etc/systemd/system/{service_name}.service"
        
        if os.geteuid() != 0:
            raise PermissionError("Creating systemd services requires root privileges")
        
        try:
            with open(service_file, 'w') as f:
                f.write(service_content)
        except IOError as e:
            raise IOError(f"Failed to write service file {service_file}: {e}")
        
        run("systemctl daemon-reload")
        run(f"systemctl enable {service_name}")
        run(f"systemctl restart {service_name}")
        
        time.sleep(1)
        result = run(f"systemctl is-active {service_name}", check=False)
        if result.returncode != 0:
            print(f"Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
        else:
            print(f"✓ Created and started scrub service: {service_name}")
        
        self.active_services[service_name] = {
            'type': 'scrub',
            'config': service_config,
            'created_at': time.time()
        }
        
        return service_name
    
    def create_sync_service(self, service_config: dict[str, Any]) -> str:
        """Create a sync service.
        
        Args:
            service_config: Configuration dictionary for sync service
            
        Returns:
            str: Service name
        """
        service_name = service_config.get('name', f"sync-{secrets.token_hex(4)}")
        
        if not self.validate_service_uniqueness(service_name):
            raise ValueError(f"Service name '{service_name}' already exists or is invalid")
        
        service_content = self._generate_sync_service_template(service_config)
        service_file = f"/etc/systemd/system/{service_name}.service"
        
        if os.geteuid() != 0:
            raise PermissionError("Creating systemd services requires root privileges")
        
        try:
            with open(service_file, 'w') as f:
                f.write(service_content)
        except IOError as e:
            raise IOError(f"Failed to write service file {service_file}: {e}")
        
        run("systemctl daemon-reload")
        run(f"systemctl enable {service_name}")
        run(f"systemctl restart {service_name}")
        
        time.sleep(1)
        result = run(f"systemctl is-active {service_name}", check=False)
        if result.returncode != 0:
            print(f"Warning: {service_name} may not be running. Check with: systemctl status {service_name}")
        else:
            print(f"✓ Created and started sync service: {service_name}")
        
        self.active_services[service_name] = {
            'type': 'sync',
            'config': service_config,
            'created_at': time.time()
        }
        
        return service_name
    
    def get_service_status(self, service_name: str) -> dict[str, Any]:
        """Get detailed status of a service.
        
        Args:
            service_name: Name of the service
            
        Returns:
            Dictionary with service status information
        """
        status_info: dict[str, Any] = {
            'service_name': service_name,
            'exists': False,
            'enabled': False,
            'active': False,
            'status': 'unknown',
            'description': None,
            'last_error': None
        }
        
        # Check if service exists
        result = run(f"systemctl list-unit-files {service_name}.service", check=False)
        if result.returncode != 0:
            return status_info
        
        status_info['exists'] = True
        
        # Get service status
        result = run(f"systemctl status {service_name}", check=False, capture_output=True)
        if result.returncode == 0:
            output: str = str(result.stdout)
            
            # Parse status information
            if 'loaded;' in output and 'enabled;' in output:
                status_info['enabled'] = True
            
            if 'active (running)' in output:
                status_info['active'] = True
                status_info['status'] = 'running'
            elif 'active (exited)' in output:
                status_info['active'] = True
                status_info['status'] = 'completed'
            elif 'inactive (dead)' in output:
                status_info['status'] = 'stopped'
            elif 'failed' in output:
                status_info['status'] = 'failed'
            
            # Extract description
            desc_match = re.search(r'Description:\s*(.+)$', output, re.MULTILINE)
            if desc_match:
                status_info['description'] = desc_match.group(1).strip()
            
            # Extract last error if any
            error_match = re.search(r'Active:\s*.*\n.*\s*(.+)$', output, re.MULTILINE)
            if error_match and 'error' in error_match.group(1).lower():
                status_info['last_error'] = error_match.group(1).strip()
        
        return status_info
    
    def list_backup_services(self) -> list[str]:
        """List all backup-related services.
        
        Returns:
            List of backup service names
        """
        services: list[str] = []
        try:
            result = run("systemctl list-units --type=service --all", check=False, capture_output=True)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if '.service' in line and ('backup' in line.lower() or 'sync' in line.lower()):
                        service_match = re.search(r'([a-zA-Z0-9_-]+)\.service', line)
                        if service_match:
                            services.append(service_match.group(1))
        except Exception as e:
            print(f"Error listing backup services: {e}")
        
        return services
    
    def stop_service(self, service_name: str) -> bool:
        """Stop a service.
        
        Args:
            service_name: Name of the service to stop
            
        Returns:
            bool: True if service stopped successfully, False otherwise
        """
        try:
            run(f"systemctl stop {service_name}")
            print(f"✓ Stopped service: {service_name}")
            return True
        except Exception as e:
            print(f"Error stopping service {service_name}: {e}")
            return False
    
    def disable_service(self, service_name: str) -> bool:
        """Disable and stop a service.
        
        Args:
            service_name: Name of the service to disable
            
        Returns:
            bool: True if service disabled successfully, False otherwise
        """
        try:
            run(f"systemctl disable {service_name}")
            run(f"systemctl stop {service_name}")
            print(f"✓ Disabled service: {service_name}")
            
            if service_name in self.active_services:
                del self.active_services[service_name]
            
            return True
        except Exception as e:
            print(f"Error disabling service {service_name}: {e}")
            return False
    
    def remove_service(self, service_name: str) -> bool:
        """Remove a service completely.
        
        Args:
            service_name: Name of the service to remove
            
        Returns:
            bool: True if service removed successfully, False otherwise
        """
        service_file = f"/etc/systemd/system/{service_name}.service"
        
        try:
            # Stop and disable first
            self.disable_service(service_name)
            
            # Remove service file
            if os.path.exists(service_file):
                os.remove(service_file)
                run("systemctl daemon-reload")
                print(f"✓ Removed service file: {service_file}")
            
            if service_name in self.active_services:
                del self.active_services[service_name]
            
            return True
        except Exception as e:
            print(f"Error removing service {service_name}: {e}")
            return False
    
    def _generate_backup_service_template(self, config: dict[str, Any]) -> str:
        """Generate backup service template."""
        source = config.get('source', '/mnt/source')
        destination = config.get('destination', '/mnt/destination')
        user = config.get('user', 'root')
        
        return f"""[Unit]
Description=Backup service for {source} to {destination}
After=network.target

[Service]
Type=oneshot
User={user}
ExecStart=/usr/bin/rsync -av --delete {source}/ {destination}/
"""
    
    def _generate_scrub_service_template(self, config: dict[str, Any]) -> str:
        """Generate scrub service template."""
        directory = config.get('directory', '/mnt/data')
        redundancy = config.get('redundancy', '10')
        user = config.get('user', 'root')
        
        return f"""[Unit]
Description=Scrub service for {directory}
After=network.target

[Service]
Type=oneshot
User={user}
ExecStart=/usr/local/bin/scrub_tool --directory {directory} --redundancy {redundancy}
"""
    
    def _generate_sync_service_template(self, config: dict[str, Any]) -> str:
        """Generate sync service template."""
        source = config.get('source', '/mnt/source')
        destination = config.get('destination', '/mnt/destination')
        user = config.get('user', 'root')
        
        return f"""[Unit]
Description=Sync service for {source} to {destination}
After=network.target

[Service]
Type=oneshot
User={user}
ExecStart=/usr/bin/rsync -av {source}/ {destination}/
"""
    
    def get_active_services_info(self) -> dict[str, dict[str, Any]]:
        """Get information about all active services.
        
        Returns:
            Dictionary with active services information
        """
        return self.active_services.copy()
    
    def export_service_config(self, service_name: str) -> Optional[dict[str, Any]]:
        """Export service configuration for backup/migration.
        
        Args:
            service_name: Name of service to export
            
        Returns:
            Service configuration if found, None otherwise
        """
        if service_name in self.active_services:
            return self.active_services[service_name].copy()
        
        return None
    
    def import_service_config(self, config: dict[str, Any]) -> Optional[str]:
        """Import service configuration and create service.
        
        Args:
            config: Service configuration to import
            
        Returns:
            Service name if successful, None otherwise
        """
        service_type = config.get('type')
        service_config = config.get('config', {})
        
        if service_type == 'backup':
            return self.create_backup_service(service_config)
        elif service_type == 'scrub':
            return self.create_scrub_service(service_config)
        elif service_type == 'sync':
            return self.create_sync_service(service_config)
        else:
            print(f"Unknown service type: {service_type}")
            return None


def get_service_manager(base_config: SetupConfig) -> ServiceManager:
    """Get service manager instance.
    
    Args:
        base_config: Base setup configuration
        
    Returns:
        ServiceManager instance
    """
    return ServiceManager(base_config)