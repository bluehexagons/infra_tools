"""Deployment steps for web applications on remote systems."""

from __future__ import annotations
import os
import shlex
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.deployment import DeploymentOrchestrator
from lib.remote_utils import run

DEPLOY_USER = "web-deploy"
DEPLOY_GROUP = "web-deploy"


def ensure_deploy_user(username: str) -> None:
    result = run(f"id {shlex.quote(username)}", check=False)
    if result.returncode != 0:
        print(f"  Creating deployment owner: {username}")
        home_dir = f"/var/lib/infra_tools/{username}"
        run("mkdir -p /var/lib/infra_tools")
        run(
            "useradd --system --user-group "
            f"--home-dir {shlex.quote(home_dir)} --create-home "
            f"--shell /usr/sbin/nologin {shlex.quote(username)}"
        )


def deploy_repository(source_path: str, deploy_spec: str, git_url: str,
                      commit_hash: Optional[str] = None, full_deploy: bool = True,
                      deploy_user: str = DEPLOY_USER, deploy_group: str = DEPLOY_GROUP,
                      keep_source: bool = False, api_subdomain: bool = False,
                      reset_migrations: bool = False, **_ : Any) -> list[dict[str, Any]]:
    """Deploy a repository, returning one nginx descriptor per served component.

    A repo with an ``infra.json`` manifest yields one descriptor per component
    (e.g. a static site plus a reverse-proxied API). Without a manifest the
    legacy single-project detection path runs and yields one descriptor.
    """
    from lib.deploy_utils import parse_deploy_spec
    from lib.project_manifest import load_manifest

    ensure_deploy_user(deploy_user)

    domain, path = parse_deploy_spec(deploy_spec)

    print(f"Deploying {git_url} to {deploy_spec}...")

    orchestrator = DeploymentOrchestrator(
        base_dir="/var/www",
        deploy_user=deploy_user,
        deploy_group=deploy_group,
    )

    manifest = load_manifest(source_path)
    if manifest is not None:
        print(f"  Detected infra.json manifest with {len(manifest.components)} component(s)")
        return orchestrator.deploy_manifest(
            manifest=manifest,
            source_path=source_path,
            domain=domain,
            path=path,
            git_url=git_url,
            commit_hash=commit_hash,
            keep_source=keep_source,
        )

    deployment_info = orchestrator.deploy_from_archive(
        source_path=source_path,
        domain=domain,
        path=path,
        git_url=git_url,
        commit_hash=commit_hash,
        full_deploy=full_deploy,
        keep_source=keep_source,
        api_subdomain=api_subdomain,
        reset_migrations=reset_migrations
    )

    return [deployment_info] if deployment_info else []
