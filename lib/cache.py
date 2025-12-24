#!/usr/bin/env python3

"""Cache and persistence utilities for setup configurations."""

import hashlib
import json
import os
from dataclasses import asdict
from typing import Optional, Dict, Any

from lib.config import SetupConfig


SETUP_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/setups")


def get_cache_path_for_host(host: str) -> str:
    """Get the cache file path for a given host."""
    os.makedirs(SETUP_CACHE_DIR, exist_ok=True)
    normalized_host = host.lower().rstrip('.')
    host_hash = hashlib.sha256(normalized_host.encode()).hexdigest()[:8]
    return os.path.join(SETUP_CACHE_DIR, f"{host}_{host_hash}.json")


def save_setup_command(config: SetupConfig) -> None:
    """Save setup configuration to cache."""
    cache_path = get_cache_path_for_host(config.host)
    
    cache_data = {
        "host": config.host,
        "system_type": config.system_type,
        "args": config.to_dict(),
        "script": f"setup_{config.system_type}.py"
    }
    
    # Add name and tags at top level for easier access
    if config.friendly_name:
        cache_data["name"] = config.friendly_name
    if config.tags:
        cache_data["tags"] = config.tags
    
    with open(cache_path, 'w') as f:
        json.dump(cache_data, f, indent=2)


def load_setup_command(host: str) -> Optional[SetupConfig]:
    """Load setup configuration from cache."""
    cache_path = get_cache_path_for_host(host)
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            system_type = data.get('system_type')
            args_dict = data.get('args', {})
            return SetupConfig.from_dict(host, system_type, args_dict)
    except Exception as e:
        print(f"Warning: Failed to load cached setup for {host}: {e}")
        return None


def merge_setup_configs(cached_config: SetupConfig, new_config: SetupConfig) -> SetupConfig:
    """Merge two SetupConfig objects, with new_config taking precedence."""
    merged_dict = asdict(cached_config)
    new_dict = asdict(new_config)
    
    for key, value in new_dict.items():
        # Skip host and system_type as they should remain from cached
        if key in ('host', 'system_type'):
            continue
            
        # Handle deploy_specs merging
        if key == 'deploy_specs' and key in merged_dict:
            if merged_dict[key] is None:
                merged_dict[key] = value
            elif value is not None:
                existing_deploys = {(spec[0], spec[1]) for spec in merged_dict[key]}
                for deploy_spec in value:
                    deploy_tuple = (deploy_spec[0], deploy_spec[1])
                    if deploy_tuple not in existing_deploys:
                        merged_dict[key].append(deploy_spec)
                        existing_deploys.add(deploy_tuple)
        # Handle samba_shares merging
        elif key == 'samba_shares' and key in merged_dict:
            if merged_dict[key] is None:
                merged_dict[key] = value
            elif value is not None:
                existing_shares = {tuple(share) for share in merged_dict[key]}
                for share_spec in value:
                    share_tuple = tuple(share_spec)
                    if share_tuple not in existing_shares:
                        merged_dict[key].append(share_spec)
                        existing_shares.add(share_tuple)
        # Handle tags merging
        elif key == 'tags':
            if value is not None:
                merged_dict[key] = value
        # For all other fields, new value takes precedence if not None
        elif value is not None:
            merged_dict[key] = value
    
    return SetupConfig(**merged_dict)
