"""Shared deployment utilities for both local and remote environments."""

import os
import re
import shlex


def parse_deploy_spec(deploy_spec: str) -> tuple:
    """
    Parse deployment specification into domain/path components.
    
    Args:
        deploy_spec: Either "domain.com/path" or "/path"
    
    Returns:
        Tuple of (domain, path) where domain may be None for local paths
    
    Examples:
        "my.example.com/blog" -> ("my.example.com", "/blog")
        "example.com" -> ("example.com", "/")
        "/blog" -> (None, "/blog")
    """
    if deploy_spec.startswith('/'):
        # Local path only
        return (None, deploy_spec)
    
    # Domain with optional path
    parts = deploy_spec.split('/', 1)
    domain = parts[0]
    path = '/' + parts[1] if len(parts) > 1 else '/'
    
    return (domain, path)


def create_safe_directory_name(domain: str, path: str) -> str:
    """
    Create a safe directory name from domain and path.
    
    Args:
        domain: Domain name (e.g., "my.example.com") or None
        path: Path (e.g., "/blog")
    
    Returns:
        Safe directory name (e.g., "my.example.com__blog")
    
    Examples:
        ("my.example.com", "/blog") -> "my.example.com__blog"
        ("example.com", "/") -> "example.com"
        (None, "/blog") -> "blog"
    """
    if domain is None:
        # No domain, just sanitize the path
        safe_path = path.strip('/').replace('/', '_')
        return safe_path if safe_path else 'root'
    
    # Sanitize domain and path
    safe_domain = domain.replace('.', '_')
    safe_path = path.strip('/').replace('/', '_')
    
    if safe_path:
        return f"{safe_domain}__{safe_path}"
    else:
        return safe_domain


def detect_project_type(repo_path: str) -> str:
    """
    Detect project type based on files in the repository.
    
    Returns:
        - "rails" for Ruby on Rails projects (.ruby-version)
        - "node" for Node.js projects (package.json)
        - "static" for static sites (index.html)
        - "unknown" if type cannot be determined
    """
    if os.path.exists(os.path.join(repo_path, ".ruby-version")):
        return "rails"
    elif os.path.exists(os.path.join(repo_path, "package.json")):
        return "node"
    elif os.path.exists(os.path.join(repo_path, "index.html")):
        return "static"
    return "unknown"


def get_project_root(repo_path: str, project_type: str) -> str:
    """
    Get the root directory for serving the project.
    
    For Node.js projects with a build output, this might be "dist" or "build".
    For static projects, this is the repo root.
    For Rails projects, this is the public directory.
    
    Args:
        repo_path: Path to the repository
        project_type: Type of project (rails, node, static)
    
    Returns:
        Path to the directory that should be served
    """
    if project_type == "rails":
        # Rails serves from the public directory
        public_dir = os.path.join(repo_path, "public")
        if os.path.exists(public_dir):
            return public_dir
        return repo_path
    
    elif project_type == "node":
        # Check for common build output directories
        for build_dir in ["dist", "build", "out"]:
            full_path = os.path.join(repo_path, build_dir)
            if os.path.exists(full_path):
                return full_path
        # If no build directory found, use repo root
        return repo_path
    
    # Static sites serve from repo root
    return repo_path


def should_reverse_proxy(project_type: str) -> bool:
    """
    Determine if the project should be reverse proxied or served statically.
    
    Args:
        project_type: Type of project (rails, node, static)
    
    Returns:
        True if the project should be reverse proxied, False if served statically
    """
    # Rails applications need to be reverse proxied
    if project_type == "rails":
        return True
    
    # Node.js and static sites are served as static files
    return False
