"""Deployment steps for web applications on remote systems."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.deployment import DeploymentOrchestrator
from shared.nginx_config import create_nginx_site
from .utils import run


def ensure_app_user(username: str) -> None:
    result = run(f"id {username}", check=False)
    if result.returncode != 0:
        print(f"  Creating application user: {username}")
        run(f"useradd -m -s /bin/bash {username}")


def deploy_repository(source_path: str, deploy_spec: str, git_url: str, 
                      commit_hash: str = None, full_deploy: bool = True,
                      web_user: str = "rails", web_group: str = "rails", 
                      keep_source: bool = False, api_subdomain: bool = False, **_) -> None:
    from shared.deploy_utils import parse_deploy_spec
    
    ensure_app_user(web_user)
    
    domain, path = parse_deploy_spec(deploy_spec)
    
    print(f"Deploying {git_url} to {deploy_spec}...")
    
    orchestrator = DeploymentOrchestrator(
        base_dir="/var/www",
        web_user=web_user,
        web_group=web_group
    )
    
    deployment_info = orchestrator.deploy_from_archive(
        source_path=source_path,
        domain=domain,
        path=path,
        git_url=git_url,
        commit_hash=commit_hash,
        run_func=run,
        full_deploy=full_deploy,
        keep_source=keep_source,
        api_subdomain=api_subdomain
    )
    
    return deployment_info

