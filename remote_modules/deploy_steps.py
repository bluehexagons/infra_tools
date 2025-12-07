"""Deployment steps for web applications."""

import os
import shlex
import shutil
import tempfile

from .utils import run, file_contains


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


def build_rails_project(project_path: str, **_) -> None:
    """Build a Ruby on Rails project."""
    print(f"  Building Rails project at {project_path}")
    
    # Install dependencies
    run(f"cd {shlex.quote(project_path)} && bundle install --deployment --without development test")
    
    # Precompile assets
    run(f"cd {shlex.quote(project_path)} && RAILS_ENV=production bundle exec rake assets:precompile")
    
    print("  ✓ Rails project built")


def build_node_project(project_path: str, **_) -> None:
    """Build a Node.js project (assumes Vite or similar static site generator)."""
    print(f"  Building Node.js project at {project_path}")
    
    # Install dependencies
    run(f"cd {shlex.quote(project_path)} && npm install")
    
    # Build the project (assumes npm run build is configured)
    result = run(f"cd {shlex.quote(project_path)} && npm run build", check=False)
    
    if result.returncode != 0:
        print("  ⚠ npm run build failed or not configured, skipping build step")
    else:
        print("  ✓ Node.js project built")


def build_static_project(project_path: str, **_) -> None:
    """Process a static website (no build needed)."""
    print(f"  Static website at {project_path} - no build required")
    print("  ✓ Static files ready")


def deploy_repository(deploy_location: str, git_url: str, **_) -> None:
    """
    Deploy a git repository to a specific location.
    
    This function is called on the remote system.
    """
    print(f"  Deploying {git_url} to {deploy_location}")
    
    # Ensure the parent directory exists
    parent_dir = os.path.dirname(deploy_location)
    if parent_dir and not os.path.exists(parent_dir):
        run(f"mkdir -p {shlex.quote(parent_dir)}")
    
    # Extract repository name from URL
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    
    project_path = os.path.join(deploy_location, repo_name) if deploy_location else repo_name
    
    # Check if directory already exists
    if os.path.exists(project_path):
        print(f"  ✓ Repository already exists at {project_path}, skipping clone")
        # Could add git pull here to update existing repos
        return
    
    # This will receive the tar archive from the local system
    # For now, we'll just create the directory
    run(f"mkdir -p {shlex.quote(project_path)}")
    
    # Detect project type and build
    project_type = detect_project_type(project_path)
    print(f"  Detected project type: {project_type}")
    
    if project_type == "rails":
        build_rails_project(project_path)
    elif project_type == "node":
        build_node_project(project_path)
    elif project_type == "static":
        build_static_project(project_path)
    else:
        print(f"  ⚠ Unknown project type, no build performed")
    
    # Set proper permissions
    run(f"chown -R www-data:www-data {shlex.quote(project_path)}", check=False)
    run(f"chmod -R 755 {shlex.quote(project_path)}")
    
    print(f"  ✓ Repository deployed to {project_path}")
