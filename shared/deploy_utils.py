"""Shared deployment utilities for both local and remote environments."""

import os
import re
import shlex


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

    # For static/unknown projects, prefer public/ if present (many frameworks place built assets there)
    if os.path.exists(os.path.join(repo_path, 'public')):
        return os.path.join(repo_path, 'public')

    return repo_path


def should_reverse_proxy(project_type: str) -> bool:
    """Determine if project should be reverse proxied (Rails) or served statically."""
    return project_type == "rails"

