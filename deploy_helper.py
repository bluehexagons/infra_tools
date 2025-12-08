#!/usr/bin/env python3
"""
Remote deployment helper script.
Uploaded to the remote system to handle repository deployments.
"""

import sys
import os
import shlex
import json

# Add the infra_tools directory to path
sys.path.insert(0, '/opt/infra_tools')

from remote_modules.deploy_steps import deploy_repository


def main():
    """Deploy repositories from command line arguments."""
    if len(sys.argv) < 2:
        print("Usage: deploy_helper.py <deployments_json>")
        sys.exit(1)
    
    # Parse deployment specifications
    deployments_json = sys.argv[1]
    deployments = json.loads(deployments_json)
    
    # Deploy each repository
    for deploy_spec, git_url in deployments:
        repo_name = git_url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        
        source_path = f'/tmp/deployments/{repo_name}'
        
        if not os.path.exists(source_path):
            print(f"Warning: Source path {source_path} not found, skipping...")
            continue
        
        deploy_repository(
            source_path=source_path,
            deploy_spec=deploy_spec,
            git_url=git_url
        )


if __name__ == '__main__':
    main()
