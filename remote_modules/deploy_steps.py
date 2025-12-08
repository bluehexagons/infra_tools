"""Deployment steps for web applications on remote systems."""

import os
import sys

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.deployment import DeploymentOrchestrator
from shared.nginx_config import create_nginx_site
from .utils import run


def deploy_repository(source_path: str, deploy_spec: str, git_url: str, 
                      web_user: str = "www-data", web_group: str = "www-data", **_) -> None:
    """
    Deploy a repository from an extracted archive.
    
    Args:
        source_path: Path to the extracted repository
        deploy_spec: Deployment specification (domain/path or /path)
        git_url: Git repository URL
        web_user: Web server user
        web_group: Web server group
    """
    from shared.deploy_utils import parse_deploy_spec
    
    # Parse deployment specification
    domain, path = parse_deploy_spec(deploy_spec)
    
    print(f"Deploying {git_url} to {deploy_spec}...")
    
    # Create orchestrator
    orchestrator = DeploymentOrchestrator(
        base_dir="/var/www",
        web_user=web_user,
        web_group=web_group
    )
    
    # Deploy the repository
    deployment_info = orchestrator.deploy_from_archive(
        source_path=source_path,
        domain=domain,
        path=path,
        git_url=git_url,
        run_func=run
    )
    
    # Configure nginx if domain is provided
    if domain:
        print(f"  Configuring nginx for {domain}{path}...")
        try:
            create_nginx_site(
                domain=domain,
                path=path,
                serve_path=deployment_info['serve_path'],
                needs_proxy=deployment_info['needs_proxy'],
                proxy_port=3000 if deployment_info['needs_proxy'] else None,
                run_func=run
            )
        except (OSError, PermissionError, ValueError) as e:
            print(f"  ⚠ Failed to configure nginx: {e}")
    
    print(f"  ✓ Deployment complete")
