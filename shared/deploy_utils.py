"""Shared deployment utilities for both local and remote environments."""

import json
import os
import re
import shlex
import subprocess
from typing import Optional


def parse_deploy_spec(deploy_spec: str) -> tuple:
    """Parse deployment spec into (domain, path). Returns (None, path) for local paths."""
    if deploy_spec.startswith('/'):
        return (None, deploy_spec)
    
    parts = deploy_spec.split('/', 1)
    domain = parts[0]
    path = '/' + parts[1] if len(parts) > 1 else '/'
    
    return (domain, path)


def create_safe_directory_name(domain: str, path: str) -> str:
    """Create safe directory name from domain and path."""
    if domain is None:
        safe_path = path.strip('/').replace('/', '_')
        return safe_path if safe_path else 'root'
    
    safe_domain = domain.replace('.', '_')
    safe_path = path.strip('/').replace('/', '_')
    
    if safe_path:
        return f"{safe_domain}__{safe_path}"
    else:
        return safe_domain


def detect_project_type(repo_path: str) -> str:
    """Detect project type: rails, node, static, or unknown."""
    # Detect Rails projects more robustly: check common Rails files or Gemfile.
    if os.path.exists(os.path.join(repo_path, ".ruby-version")):
        return "rails"

    gemfile = os.path.join(repo_path, "Gemfile")
    if os.path.exists(gemfile):
        try:
            with open(gemfile, 'r') as f:
                content = f.read()
                if 'rails' in content:
                    return 'rails'
        except Exception:
            pass

    # config/environment.rb or config.ru are also strong indicators of a Rails app
    if os.path.exists(os.path.join(repo_path, 'config', 'environment.rb')) or os.path.exists(os.path.join(repo_path, 'config.ru')):
        return 'rails'

    # Node projects
    if os.path.exists(os.path.join(repo_path, "package.json")):
        return "node"

    # Static sites: index at repo root or inside public/
    if os.path.exists(os.path.join(repo_path, "index.html")) or os.path.exists(os.path.join(repo_path, "public", "index.html")):
        return "static"

    # If there's a public directory (common for Rails), assume rails
    if os.path.exists(os.path.join(repo_path, 'public')):
        return 'rails'

    return "unknown"


def get_project_root(repo_path: str, project_type: str) -> str:
    """Get the root directory for serving the project."""
    if project_type == "rails":
        public_dir = os.path.join(repo_path, "public")
        if os.path.exists(public_dir):
            return public_dir
        # Fall back: if there's an index.html at repo root, serve that directory
        if os.path.exists(os.path.join(repo_path, 'index.html')):
            return repo_path
        return repo_path
    
    elif project_type == "node":
        for build_dir in ["dist", "build", "out"]:
            full_path = os.path.join(repo_path, build_dir)
            if os.path.exists(full_path):
                return full_path
        return repo_path

    # For static/unknown projects, prefer html/, public/, or static/ if present
    for static_dir in ["html", "public", "static"]:
        full_path = os.path.join(repo_path, static_dir)
        if os.path.exists(full_path):
            return full_path

    return repo_path


def should_reverse_proxy(project_type: str) -> bool:
    """Determine if project should be reverse proxied (Rails) or served statically."""
    return project_type == "rails"


def get_git_commit_hash(repo_path: str) -> Optional[str]:
    """Get current git commit hash from a repository directory."""
    git_dir = os.path.join(repo_path, '.git')
    
    # Check if .git exists (might be a file in worktrees or might not exist)
    if not os.path.exists(git_dir):
        return None
    
    try:
        result = subprocess.run(
            ['git', '-C', repo_path, 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    
    return None


def get_deployment_metadata_path(deployment_path: str) -> str:
    """Get path to deployment metadata file."""
    return os.path.join(deployment_path, '.deploy_metadata.json')


def save_deployment_metadata(deployment_path: str, git_url: str, commit_hash: Optional[str]) -> None:
    """Save deployment metadata to track versions."""
    metadata = {
        'git_url': git_url,
        'commit_hash': commit_hash
    }
    metadata_path = get_deployment_metadata_path(deployment_path)
    
    try:
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        print(f"  ⚠ Warning: Could not save deployment metadata: {e}")


def load_deployment_metadata(deployment_path: str) -> Optional[dict]:
    """Load deployment metadata if it exists."""
    metadata_path = get_deployment_metadata_path(deployment_path)
    
    if not os.path.exists(metadata_path):
        return None
    
    try:
        with open(metadata_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def should_redeploy(deployment_path: str, git_url: str, new_commit_hash: Optional[str], full_deploy: bool) -> bool:
    """Determine if a deployment should be rebuilt.
    
    Args:
        deployment_path: Path to the existing deployment
        git_url: Git URL being deployed
        new_commit_hash: Commit hash of the new deployment
        full_deploy: If True, always redeploy
    
    Returns:
        True if should redeploy, False to skip
    """
    if full_deploy:
        return True
    
    if not os.path.exists(deployment_path):
        return True
    
    if new_commit_hash is None:
        # No version info available, deploy to be safe
        return True
    
    metadata = load_deployment_metadata(deployment_path)
    if metadata is None:
        # No previous metadata, deploy to be safe
        return True
    
    if metadata.get('git_url') != git_url:
        # Different repository, definitely redeploy
        return True
    
    if metadata.get('commit_hash') != new_commit_hash:
        # Different version, redeploy
        return True
    
    # Same version, skip
    return False

