"""Deployment orchestration - shared between local and remote environments."""

import os
import shlex
import shutil
from typing import Optional

from .deploy_utils import (
    parse_deploy_spec,
    create_safe_directory_name,
    detect_project_type,
    get_project_root,
    should_reverse_proxy
)


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
                           git_url: str, run_func) -> dict:
        dest_path = self.get_deployment_path(domain, path, git_url)
        
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
        
        result = run_func(f"chown -R {shlex.quote(self.web_user)}:{shlex.quote(self.web_group)} {shlex.quote(dest_path)}", check=False)
        if result.returncode != 0:
            print(f"  ⚠ Warning: Could not set ownership to {self.web_user}:{self.web_group}")
        
        run_func(f"chmod -R 755 {shlex.quote(dest_path)}")
        
        print(f"  ✓ Repository deployed to {dest_path}")
        
        return {
            'dest_path': dest_path,
            'domain': domain,
            'path': path,
            'project_type': project_type,
            'serve_path': get_project_root(dest_path, project_type),
            'needs_proxy': should_reverse_proxy(project_type)
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
        
        run_func(f"cd {shlex.quote(project_path)} && bundle install --deployment --without development test")
        run_func(f"cd {shlex.quote(project_path)} && RAILS_ENV=production bundle exec rake assets:precompile")
        
        print("  ✓ Rails project built")
    
    def _build_node_project(self, project_path: str, run_func):
        print(f"  Building Node.js project at {project_path}")
        
        run_func(f"cd {shlex.quote(project_path)} && npm install")
        
        result = run_func(f"cd {shlex.quote(project_path)} && npm run build", check=False)
        
        if result.returncode != 0:
            print("  ⚠ npm run build failed or not configured, skipping build step")
        else:
            print("  ✓ Node.js project built")
    
    def _build_static_project(self, project_path: str):
        print(f"  Static website at {project_path} - no build required")
        print("  ✓ Static files ready")

