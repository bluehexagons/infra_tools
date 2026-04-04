#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from typing import Optional, Any

from lib.config import SetupConfig
from lib.workspace import DEFAULT_WORKSPACE_DIR, get_setup_cache_dir


SETUP_CACHE_DIR = os.path.join(DEFAULT_WORKSPACE_DIR, "setups")


def get_cache_path_for_host(host: str) -> str:
    cache_dir = get_setup_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    normalized_host = host.lower().rstrip('.')
    safe_host = re.sub(r'[^a-zA-Z0-9._-]', '_', normalized_host)
    host_hash = hashlib.sha256(normalized_host.encode()).hexdigest()[:8]
    return os.path.join(cache_dir, f"{safe_host}_{host_hash}.json")


def save_setup_command(config: SetupConfig, start_time: Optional[float] = None, 
                      end_time: Optional[float] = None, success: Optional[bool] = None) -> None:
    cache_path = get_cache_path_for_host(config.host)
    
    cache_data: dict[str, Any] = {
        "host": config.host,
        "system_type": config.system_type,
        "args": config.to_dict(),
        "script": f"setup_{config.system_type}.py"
    }
    
    if config.friendly_name:
        cache_data["name"] = config.friendly_name
    if config.tags:
        cache_data["tags"] = config.tags
        
    # Add metadata if provided
    if start_time is not None:
        cache_data["last_start_time"] = start_time
    if end_time is not None:
        cache_data["last_end_time"] = end_time
    if success is not None:
        cache_data["last_success"] = success
    
    with open(cache_path, 'w') as f:
        json.dump(cache_data, f, indent=2)


def _load_cache_file(cache_path: str, host: str) -> Optional[SetupConfig]:
    """Load a SetupConfig from a cache file, using the provided host string."""
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            system_type = data.get('system_type')
            args_dict = data.get('args', {})
            if 'name' in data and 'friendly_name' not in args_dict:
                args_dict['friendly_name'] = data['name']
            if 'tags' in data and 'tags' not in args_dict:
                args_dict['tags'] = data['tags']
            return SetupConfig.from_dict(host, system_type, args_dict)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        print(f"Warning: Failed to load cached setup for {host}: {e}")
        return None


def _find_cache_by_name(name: str) -> Optional[SetupConfig]:
    """Search all cache files for one matching by friendly name or tag."""
    cache_dir = get_setup_cache_dir()
    if not os.path.exists(cache_dir):
        return None
    needle = name.lower()
    try:
        for filename in os.listdir(cache_dir):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(cache_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
            except Exception:
                continue
            cached_name = str(data.get('name', '')).lower()
            if needle == cached_name:
                actual_host = data.get('host', '')
                if actual_host:
                    return _load_cache_file(filepath, actual_host)
                continue
            tags = data.get('tags', [])
            if isinstance(tags, list) and any(needle == str(t).lower() for t in tags):
                actual_host = data.get('host', '')
                if actual_host:
                    return _load_cache_file(filepath, actual_host)
    except Exception:
        pass
    return None


def load_setup_command(host: str) -> Optional[SetupConfig]:
    cache_path = get_cache_path_for_host(host)
    if os.path.exists(cache_path):
        return _load_cache_file(cache_path, host)
    # Fall back to searching by friendly name / tag so callers can use
    # names like "devweb" instead of the raw IP address.
    return _find_cache_by_name(host)


def merge_setup_configs(cached_config: SetupConfig, new_config: SetupConfig) -> SetupConfig:
    merged_dict = asdict(cached_config)
    new_dict = asdict(new_config)
    
    for key, value in new_dict.items():
        if key in ('host', 'system_type'):
            continue
            
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
        elif key == 'share_credentials' and key in merged_dict:
            if merged_dict[key] is None:
                merged_dict[key] = value
            elif value is not None:
                merged_credentials = {
                    credential_spec[0]: credential_spec
                    for credential_spec in merged_dict[key]
                    if credential_spec and len(credential_spec) >= 2
                }
                for credential_spec in value:
                    if credential_spec and len(credential_spec) >= 2:
                        merged_credentials[credential_spec[0]] = credential_spec
                merged_dict[key] = list(merged_credentials.values())
        elif key == 'tags':
            if value is not None:
                merged_dict[key] = value
        elif value is not None:
            merged_dict[key] = value
    
    return SetupConfig(**merged_dict)
