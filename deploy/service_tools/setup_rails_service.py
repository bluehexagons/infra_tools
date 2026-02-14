#!/usr/bin/env python3
"""Manual systemd service setup for deployed Rails applications."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from lib.systemd_service import create_rails_service, create_node_service
from lib.remote_utils import run


def main():
    app_path = "/var/www/root"
    app_name = "root"
    
    if not os.path.exists(app_path):
        print(f"Error: {app_path} does not exist")
        sys.exit(1)
    
    print("Setting up services for existing deployment...")
    print(f"App path: {app_path}")
    print(f"App name: {app_name}")
    print()
    
    try:
        run("id rails || useradd -m -s /bin/bash rails", check=False)
        
        create_rails_service(app_name, app_path, 3000, "rails", "rails")
        
        frontend_path = os.path.join(app_path, "frontend")
        if os.path.exists(frontend_path):
            print(f"\nDetected frontend at {frontend_path}")
            create_node_service(app_name, frontend_path, 4000, "rails", "rails")
            
        print("\n✓ Service setup complete!")
        print("\nYou can check the service status with:")
        print(f"  systemctl status rails-{app_name}")
        if os.path.exists(frontend_path):
            print(f"  systemctl status node-{app_name}")
        return 0
    except Exception as e:
        print(f"\n✗ Error setting up service: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
