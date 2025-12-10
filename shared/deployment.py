"""Deployment orchestration - shared between local and remote environments."""

import os
import shlex
import shutil
import secrets
import re
import socket
from typing import Optional, Set

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
    
    def _get_used_ports(self) -> Set[int]:
        """Get set of ports currently used by infra_tools services."""
        used_ports = set()
        try:
            if not os.path.exists("/etc/systemd/system"):
                return used_ports
                
            files = os.listdir("/etc/systemd/system")
            for f in files:
                if (f.startswith("rails-") or f.startswith("node-")) and f.endswith(".service"):
                    path = os.path.join("/etc/systemd/system", f)
                    try:
                        with open(path, 'r') as service_file:
                            content = service_file.read()
                            # Rails: -p {port}
                            match = re.search(r'-p (\d+)', content)
                            if match:
                                used_ports.add(int(match.group(1)))
                            # Node: --port {port}
                            match = re.search(r'--port (\d+)', content)
                            if match:
                                used_ports.add(int(match.group(1)))
                    except Exception:
                        pass
        except Exception:
            pass
        return used_ports

    def _find_free_port(self, start_port: int) -> int:
        """Find the first free port starting from start_port."""
        used_ports = self._get_used_ports()
        port = start_port
        while port < 65535:
            if port in used_ports:
                port += 1
                continue
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', port))
                    return port
                except OSError:
                    port += 1
        raise RuntimeError("No free ports available")

    def _get_assigned_port(self, service_name: str, default_port: int) -> int:
        """Get the port assigned to a service, or find a new free one."""
        service_file = f"/etc/systemd/system/{service_name}.service"
        if os.path.exists(service_file):
            try:
                with open(service_file, 'r') as f:
                    content = f.read()
                    # Rails
                    match = re.search(r'-p (\d+)', content)
                    if match:
                        return int(match.group(1))
                    # Node
                    match = re.search(r'--port (\d+)', content)
                    if match:
                        return int(match.group(1))
            except Exception:
                pass
        
        return self._find_free_port(default_port)

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
                           full_deploy: bool = True, keep_source: bool = False) -> dict:
        dest_path = self.get_deployment_path(domain, path, git_url)
        
        # Check if we should skip this deployment
        if should_redeploy(dest_path, git_url, commit_hash, full_deploy):
            print(f"Deploying to {dest_path}...")
        else:
            print(f"Skipping {dest_path} (already at commit {commit_hash})...")
            
            # Still return deployment info for nginx configuration
            project_type = detect_project_type(dest_path)
            
            frontend_serve_path = None
            if project_type == "rails":
                frontend_path = os.path.join(dest_path, "frontend")
                if os.path.exists(frontend_path):
                    frontend_serve_path = get_project_root(frontend_path, "node")

            return {
                'dest_path': dest_path,
                'domain': domain,
                'path': path,
                'project_type': project_type,
                'serve_path': get_project_root(dest_path, project_type),
                'needs_proxy': should_reverse_proxy(project_type),
                'backend_port': 3000 if project_type == "rails" else None,
                'frontend_port': 4000 if project_type == "rails" and os.path.exists(os.path.join(dest_path, "frontend")) else None,
                'frontend_serve_path': frontend_serve_path,
                'skipped': True
            }
        
        print(f"Deploying to {dest_path}...")
        
        parent_dir = os.path.dirname(dest_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        if os.path.exists(dest_path):
            print(f"  Removing existing deployment at {dest_path}...")
            shutil.rmtree(dest_path)
        
        if keep_source:
            shutil.copytree(source_path, dest_path)
            print(f"  ✓ Copied to {dest_path}")
        else:
            shutil.move(source_path, dest_path)
            print(f"  ✓ Moved to {dest_path}")
        
        project_type = detect_project_type(dest_path)
        print(f"  Detected project type: {project_type}")
        
        site_root = path or "/"
        if not site_root.startswith("/"):
            site_root = f"/{site_root}"
        if not site_root.endswith("/"):
            site_root = f"{site_root}/"
        
        self.build_project(dest_path, project_type, run_func, site_root=site_root)
        
        # Set up systemd service for Rails apps
        backend_port = None
        frontend_port = None
        frontend_serve_path = None
        
        if project_type == "rails":
            app_name = os.path.basename(dest_path)
            
            # Determine port
            service_name = f"rails-{app_name}"
            backend_port = self._get_assigned_port(service_name, 3000)
            
            # Determine allowed origins for CORS
            cors_origins = []
            if domain:
                cors_origins.append(f"https://{domain}")
                cors_origins.append(f"https://www.{domain}")
                cors_origins.append(f"http://{domain}")
                cors_origins.append(f"http://www.{domain}")
            
            create_rails_service(app_name, dest_path, backend_port, self.web_user, self.web_group, run_func, 
                               env_vars={"CORS_ORIGINS": ",".join(cors_origins)})
            
            # Check for frontend
            frontend_path = os.path.join(dest_path, "frontend")
            if os.path.exists(frontend_path):
                print(f"  Detected frontend at {frontend_path}")
                
                # Determine API URL
                api_url = "/api"
                is_root = not path or path == '/'
                
                if is_root and domain:
                    api_url = f"https://api.{domain}"
                elif not is_root:
                    clean_path = path.rstrip('/')
                    if not clean_path.startswith('/'):
                        clean_path = '/' + clean_path
                    api_url = f"{clean_path}/api"

                site_root = path or "/"
                if not site_root.startswith("/"):
                    site_root = f"/{site_root}"
                if not site_root.endswith("/"):
                    site_root = f"{site_root}/"
                
                # Build frontend
                self._build_node_project(frontend_path, run_func, api_url, site_root)
                
                frontend_serve_path = get_project_root(frontend_path, "node")
                print(f"  Frontend will be served statically from {frontend_serve_path}")
                
                # Clear frontend_port since we are serving statically
                frontend_port = None
        
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
            'frontend_port': frontend_port,
            'frontend_serve_path': frontend_serve_path
        }
    
    def build_project(self, project_path: str, project_type: str, run_func, site_root: Optional[str] = None):
        if project_type == "rails":
            self._build_rails_project(project_path, run_func)
        elif project_type == "node":
            self._build_node_project(project_path, run_func, site_root=site_root)
        elif project_type == "static":
            self._build_static_project(project_path)
        else:
            print(f"  ⚠ Unknown project type, no build performed")
    
    def _build_rails_project(self, project_path: str, run_func):
        print(f"  Building Rails project at {project_path}")
        
        # Patch CORS configuration
        cors_file = os.path.join(project_path, "config", "initializers", "cors.rb")
        if os.path.exists(cors_file):
            print("  Patching CORS configuration...")
            try:
                with open(cors_file, 'r') as f:
                    content = f.read()
                
                if 'ENV["CORS_ORIGINS"]' not in content:
                    # Replace the specific line we saw in the repo
                    new_content = content.replace(
                        'origins "http://localhost:5173", "http://127.0.0.1:5173"',
                        'origins((ENV["CORS_ORIGINS"]&.split(",") || []) + ["http://localhost:5173", "http://127.0.0.1:5173"])'
                    )
                    # Also try a more generic replacement if the exact string doesn't match
                    if new_content == content:
                         new_content = re.sub(
                            r'origins\s+["\'].*?["\'](?:,\s*["\'].*?["\'])*',
                            'origins((ENV["CORS_ORIGINS"]&.split(",") || []) + ["http://localhost:5173", "http://127.0.0.1:5173"])',
                            content
                        )

                    with open(cors_file, 'w') as f:
                        f.write(new_content)
            except Exception as e:
                print(f"  ⚠ Failed to patch CORS configuration: {e}")
        
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
    
    def _build_node_project(self, project_path: str, run_func, api_url: Optional[str] = None, site_root: Optional[str] = None):
        print(f"  Building Node.js project at {project_path}")
        
        run_func(f"cd {shlex.quote(project_path)} && npm install")
        
        build_cmd = "npm run build"
        env_prefix = []

        if api_url:
            env_prefix.append(f"VITE_API_URL={shlex.quote(api_url)}")

        if site_root:
            normalized_root = site_root if site_root.startswith('/') else f"/{site_root}"
            if not normalized_root.endswith('/'):
                normalized_root = f"{normalized_root}/"
            env_prefix.append(f"VITE_SITE_ROOT={shlex.quote(normalized_root)}")
            build_cmd = f"{build_cmd} -- --base {shlex.quote(normalized_root)}"

        if env_prefix:
            build_cmd = f"{' '.join(env_prefix)} {build_cmd}"
        
        result = run_func(f"cd {shlex.quote(project_path)} && {build_cmd}", check=False)
        
        if result.returncode != 0:
            print("  ⚠ npm run build failed or not configured, skipping build step")
        else:
            print("  ✓ Node.js project built")
    
    def _build_static_project(self, project_path: str):
        print(f"  Static website at {project_path} - no build required")
        print("  ✓ Static files ready")

