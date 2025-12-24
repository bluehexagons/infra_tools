#!/usr/bin/env python3

"""Configuration dataclass for setup operations."""

import argparse
import getpass
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Any


@dataclass
class SetupConfig:
    """Configuration for a setup operation."""
    host: str
    username: str
    system_type: str
    password: Optional[str] = None
    ssh_key: Optional[str] = None
    timezone: str = "UTC"
    friendly_name: Optional[str] = None
    tags: Optional[List[str]] = None
    enable_rdp: bool = False
    enable_x2go: bool = False
    skip_audio: bool = False
    desktop: str = "xfce"
    browser: str = "brave"
    use_flatpak: bool = False
    install_office: bool = False
    dry_run: bool = False
    install_ruby: bool = False
    install_go: bool = False
    install_node: bool = False
    custom_steps: Optional[str] = None
    deploy_specs: Optional[List[List[str]]] = None
    full_deploy: bool = False
    enable_ssl: bool = False
    ssl_email: Optional[str] = None
    enable_cloudflare: bool = False
    api_subdomain: bool = False
    enable_samba: bool = False
    samba_shares: Optional[List[List[str]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding host and system_type."""
        data = asdict(self)
        data.pop('host', None)
        data.pop('system_type', None)
        # Convert tags list to comma-separated string for storage
        if self.tags:
            data['tags'] = ','.join(self.tags)
        return data
    
    @classmethod
    def from_dict(cls, host: str, system_type: str, data: Dict[str, Any]) -> 'SetupConfig':
        """Create SetupConfig from dictionary."""
        # Convert tags string to list
        tags_str = data.get('tags')
        if tags_str and isinstance(tags_str, str):
            data['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        elif not tags_str:
            data['tags'] = None
            
        # Handle friendly_name
        if 'friendly_name' not in data:
            data['friendly_name'] = None
            
        return cls(host=host, system_type=system_type, **data)
    
    @classmethod
    def from_args(cls, args: argparse.Namespace, system_type: str) -> 'SetupConfig':
        """Create SetupConfig from parsed arguments."""
        from lib.setup_common import get_current_username, get_local_timezone
        
        # Extract and process tags
        tags = None
        if hasattr(args, 'tags') and args.tags:
            tags = [tag.strip() for tag in args.tags.split(',') if tag.strip()]
        
        # Get username with default
        username = args.username if args.username else get_current_username()
        
        # Get timezone with default
        timezone = args.timezone if args.timezone else get_local_timezone()
        
        # Handle defaults for desktop and browser
        desktop = args.desktop or "xfce"
        browser = args.browser or "brave"
        
        # Handle office default for pc_dev
        install_office = args.install_office
        if system_type == "pc_dev" and install_office is None:
            install_office = True
        elif install_office is None:
            install_office = False
        
        # Handle RDP default
        enable_rdp = args.enable_rdp
        if enable_rdp is None and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
            enable_rdp = True
        elif enable_rdp is None:
            enable_rdp = False
        
        # Handle X2Go default
        enable_x2go = args.enable_x2go
        if enable_x2go is None and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
            enable_x2go = True
        elif enable_x2go is None:
            enable_x2go = False
        
        return cls(
            host=args.host,
            username=username,
            system_type=system_type,
            password=getattr(args, 'password', None),
            ssh_key=getattr(args, 'ssh_key', None),
            timezone=timezone,
            friendly_name=getattr(args, 'friendly_name', None),
            tags=tags,
            enable_rdp=enable_rdp,
            enable_x2go=enable_x2go,
            skip_audio=getattr(args, 'skip_audio', False),
            desktop=desktop,
            browser=browser,
            use_flatpak=getattr(args, 'use_flatpak', False),
            install_office=install_office,
            dry_run=getattr(args, 'dry_run', False),
            install_ruby=getattr(args, 'install_ruby', False),
            install_go=getattr(args, 'install_go', False),
            install_node=getattr(args, 'install_node', False),
            custom_steps=getattr(args, 'custom_steps', None),
            deploy_specs=getattr(args, 'deploy_specs', None),
            full_deploy=getattr(args, 'full_deploy', False),
            enable_ssl=getattr(args, 'enable_ssl', False),
            ssl_email=getattr(args, 'ssl_email', None),
            enable_cloudflare=getattr(args, 'enable_cloudflare', False),
            api_subdomain=getattr(args, 'api_subdomain', False),
            enable_samba=getattr(args, 'enable_samba', False),
            samba_shares=getattr(args, 'samba_shares', None)
        )
