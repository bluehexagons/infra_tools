"""Deployment orchestration - shared between local and remote environments."""

import os
import shlex
import shutil
import secrets
from typing import Optional

from .deploy_utils import (
    parse_deploy_spec,
    create_safe_directory_name,
    detect_project_type,
    get_project_root,
    should_reverse_proxy,
    get_git_commit_hash,
    save_deployment_metadata,
    should_redeploy
)
from .systemd_service import create_rails_service, create_node_service


class DeploymentOrchestrator:
    
    def __init__(self, base_dir: str = "/var/www", web_user: str = "www-data", web_group: str = "www-data"):
        self.base_dir = base_dir
        self.web_user = web_user
        self.web_group = web_group
    
    def get_deployment_path(self, domain: Optional[str], path: str, git_url: str) -> str:
        dir_name = create_safe_directory_name(domain, path)
        
        repo_name = git_url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        
        if dir_name:
            return os.path.join(self.base_dir, dir_name)
        else:
            return os.path.join(self.base_dir, repo_name)
    
    def deploy_from_archive(self, source_path: str, domain: Optional[str], path: str, 
                           git_url: str, commit_hash: Optional[str], run_func, 
                           full_deploy: bool = True) -> dict:
        dest_path = self.get_deployment_path(domain, path, git_url)
        
        # Check if we should skip this deployment
        if should_redeploy(dest_path, git_url, commit_hash, full_deploy):
            print(f"Deploying to {dest_path}...")
        else:
            print(f"Skipping {dest_path} (already at commit {commit_hash})...")
            
            # Still return deployment info for nginx configuration
            project_type = detect_project_type(dest_path)
            return {
                'dest_path': dest_path,
                'domain': domain,
                'path': path,
                'project_type': project_type,
                'serve_path': get_project_root(dest_path, project_type),
                'needs_proxy': should_reverse_proxy(project_type),
                'backend_port': 3000 if project_type == "rails" else None,
                'frontend_port': 4000 if project_type == "rails" and os.path.exists(os.path.join(dest_path, "frontend")) else None,
                'skipped': True
            }
        
        print(f"Deploying to {dest_path}...")
        
        parent_dir = os.path.dirname(dest_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        if os.path.exists(dest_path):
            print(f"  Removing existing deployment at {dest_path}...")
            shutil.rmtree(dest_path)
        
        shutil.move(source_path, dest_path)
        print(f"  ✓ Moved to {dest_path}")
        
        project_type = detect_project_type(dest_path)
        print(f"  Detected project type: {project_type}")
        
        self.build_project(dest_path, project_type, run_func)
        
        # Set up systemd service for Rails apps
        backend_port = None
        frontend_port = None
        
        if project_type == "rails":
            app_name = os.path.basename(dest_path)
            create_rails_service(app_name, dest_path, 3000, self.web_user, self.web_group, run_func)
            backend_port = 3000
            
            # Check for frontend
            frontend_path = os.path.join(dest_path, "frontend")
            if os.path.exists(frontend_path):
                print(f"  Detected frontend at {frontend_path}")
                
                # Determine API URL
                api_url = "/api"
                if domain:
                    api_url = f"https://api.{domain}"
                
                # Build frontend
                self._build_node_project(frontend_path, run_func, api_url)
                # Create Node service
                create_node_service(app_name, frontend_path, 4000, self.web_user, self.web_group, run_func)
                frontend_port = 4000
        
        # Fix permissions AFTER all build steps (including frontend)
        result = run_func(f"chown -R {shlex.quote(self.web_user)}:{shlex.quote(self.web_group)} {shlex.quote(dest_path)}", check=False)
        if result.returncode != 0:
            print(f"  ⚠ Warning: Could not set ownership to {self.web_user}:{self.web_group}")
        
        # Ensure write permissions for the group so the service user can write temp files
        run_func(f"chmod -R 775 {shlex.quote(dest_path)}")
        
        # Save deployment metadata
        save_deployment_metadata(dest_path, git_url, commit_hash)
        
        print(f"  ✓ Repository deployed to {dest_path}")
        
        return {
            'dest_path': dest_path,
            'domain': domain,
            'path': path,
            'project_type': project_type,
            'serve_path': get_project_root(dest_path, project_type),
            'needs_proxy': should_reverse_proxy(project_type),
            'backend_port': backend_port,
            'frontend_port': frontend_port
        }
    
    def build_project(self, project_path: str, project_type: str, run_func):
        if project_type == "rails":
            self._build_rails_project(project_path, run_func)
        elif project_type == "node":
            self._build_node_project(project_path, run_func)
        elif project_type == "static":
            self._build_static_project(project_path)
        else:
            print(f"  ⚠ Unknown project type, no build performed")
    
    def _build_rails_project(self, project_path: str, run_func):
        print(f"  Building Rails project at {project_path}")
        
        # Generate a temporary secret key for build steps
        build_secret = secrets.token_hex(64)
        env_vars = f"RAILS_ENV=production SECRET_KEY_BASE={build_secret}"
        
        run_func(f"cd {shlex.quote(project_path)} && bundle install --deployment --without development test")
        
        # Database setup
        print("  Setting up database...")
        run_func(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:create", check=False)
        run_func(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:migrate")
        
        # Only precompile assets if the task exists (skips for API-only apps)
        check_task = run_func(f"cd {shlex.quote(project_path)} && bundle exec rake -T assets:precompile | grep assets:precompile", check=False)
        if check_task.returncode == 0:
            run_func(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake assets:precompile")
        else:
            print("  ℹ Skipping assets:precompile (task not found, likely API-only app)")
        
        print("  ✓ Rails project built")
    
    def _build_node_project(self, project_path: str, run_func, api_url: Optional[str] = None):
        print(f"  Building Node.js project at {project_path}")
        
        run_func(f"cd {shlex.quote(project_path)} && npm install")
        
        build_cmd = "npm run build"
        if api_url:
            build_cmd = f"VITE_API_URL={shlex.quote(api_url)} {build_cmd}"
        
        result = run_func(f"cd {shlex.quote(project_path)} && {build_cmd}", check=False)
        
        if result.returncode != 0:
            print("  ⚠ npm run build failed or not configured, skipping build step")
        else:
            print("  ✓ Node.js project built")
    
    def _build_static_project(self, project_path: str):
        print(f"  Static website at {project_path} - no build required")
        print("  ✓ Static files ready")

