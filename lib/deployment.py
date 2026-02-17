"""Deployment orchestration - shared between local and remote environments."""

from __future__ import annotations
import os
import shlex
import shutil
import secrets
import re
import socket
import stat
import sys
from datetime import datetime
from typing import Optional, Any

from lib.remote_utils import run
from lib.deploy_utils import (
    create_safe_directory_name,
    detect_project_type,
    get_project_root,
    should_reverse_proxy,
    save_deployment_metadata,
    should_redeploy
)
from lib.systemd_service import create_rails_service


class DeploymentOrchestrator:
    
    def __init__(self, base_dir: str = "/var/www", web_user: str = "www-data", web_group: str = "www-data"):
        self.base_dir = base_dir
        self.web_user = web_user
        self.web_group = web_group

    def _get_persistent_root(self, app_name: str) -> str:
        return os.path.join(self.base_dir, ".infra_tools_shared", app_name)
    
    def _get_backup_dir(self, app_name: str) -> str:
        """Get the backup directory for database backups."""
        return os.path.join(self.base_dir, ".infra_tools_shared", app_name, "backups")

    def _ensure_dir(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def _safe_remove_path(self, path: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)

    def _is_rails_project(self, project_path: str) -> bool:
        return os.path.exists(os.path.join(project_path, "bin", "rails"))

    def _persist_rails_state_from_existing_release(self, existing_release_path: str, persistent_root: str) -> None:
        self._ensure_dir(persistent_root)

        existing_db = os.path.join(existing_release_path, "db", "production.sqlite3")
        persistent_db_dir = os.path.join(persistent_root, "db")
        self._ensure_dir(persistent_db_dir)

        if os.path.exists(existing_db) and not os.path.islink(existing_db):
            shutil.copy2(existing_db, os.path.join(persistent_db_dir, "production.sqlite3"))

        dirs_to_persist = [
            ("storage", os.path.join(persistent_root, "storage")),
            (os.path.join("public", "uploads"), os.path.join(persistent_root, "public", "uploads")),
            (os.path.join("public", "system"), os.path.join(persistent_root, "public", "system")),
            ("log", os.path.join(persistent_root, "log")),
        ]

        for rel_src, persistent_dst in dirs_to_persist:
            src_path = os.path.join(existing_release_path, rel_src)
            if not os.path.exists(src_path) or os.path.islink(src_path):
                continue
            if os.path.exists(persistent_dst):
                continue
            self._ensure_dir(os.path.dirname(persistent_dst))
            shutil.copytree(src_path, persistent_dst, symlinks=True)

    def _link_rails_persistent_state_into_release(self, release_path: str, persistent_root: str) -> None:
        """Ensure a release uses persistent storage for runtime state."""
        self._ensure_dir(persistent_root)

        persistent_db_dir = os.path.join(persistent_root, "db")
        self._ensure_dir(persistent_db_dir)
        release_db_dir = os.path.join(release_path, "db")
        self._ensure_dir(release_db_dir)

        release_db_file = os.path.join(release_db_dir, "production.sqlite3")
        persistent_db_file = os.path.join(persistent_db_dir, "production.sqlite3")
        if os.path.lexists(release_db_file) and not os.path.islink(release_db_file):
            os.remove(release_db_file)
        if not os.path.lexists(release_db_file):
            os.symlink(persistent_db_file, release_db_file)

        dirs_to_link = [
            ("storage", os.path.join(persistent_root, "storage")),
            (os.path.join("public", "uploads"), os.path.join(persistent_root, "public", "uploads")),
            (os.path.join("public", "system"), os.path.join(persistent_root, "public", "system")),
            ("log", os.path.join(persistent_root, "log")),
        ]

        for rel_path, persistent_path in dirs_to_link:
            release_path_abs = os.path.join(release_path, rel_path)
            self._ensure_dir(os.path.dirname(persistent_path))
            if not os.path.exists(persistent_path):
                if os.path.exists(release_path_abs) and not os.path.islink(release_path_abs):
                    shutil.move(release_path_abs, persistent_path)
                else:
                    self._ensure_dir(persistent_path)

            if os.path.lexists(release_path_abs):
                self._safe_remove_path(release_path_abs)
            self._ensure_dir(os.path.dirname(release_path_abs))
            os.symlink(persistent_path, release_path_abs)
    
    def _backup_database(self, db_path: str, backup_dir: str, app_name: str) -> Optional[str]:
        """Create a timestamped backup of the database.
        
        Args:
            db_path: Path to the database file to backup
            backup_dir: Directory to store backups
            app_name: Application name for backup filename
            
        Returns:
            Path to backup file if successful, None otherwise
        """
        if not os.path.exists(db_path):
            return None
        
        if os.path.islink(db_path):
            db_path = os.path.realpath(db_path)
            if not os.path.exists(db_path):
                return None
        
        self._ensure_dir(backup_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{app_name}_production_{timestamp}.sqlite3"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        try:
            print(f"  Creating database backup: {backup_filename}")
            shutil.copy2(db_path, backup_path)
            
            # Set explicit permissions: rw-rw-r-- (664)
            os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
            
            # Verify backup was created and has size > 0
            if os.path.exists(backup_path):
                backup_size_bytes = os.path.getsize(backup_path)
                if backup_size_bytes > 0:
                    backup_size_mb = backup_size_bytes / (1024 * 1024)
                    print(f"  ✓ Backup created successfully ({backup_size_mb:.2f} MB)")
                    
                    # Clean up old backups (keep last 10)
                    self._cleanup_old_backups(backup_dir, app_name, keep=10)
                    
                    return backup_path
                else:
                    print(f"  ✗ Backup verification failed: file is empty")
                    return None
            else:
                print(f"  ✗ Backup verification failed: file is missing")
                return None
                
        except (OSError, shutil.Error) as e:
            print(f"  ✗ Backup failed: {e}")
            return None
    
    def _cleanup_old_backups(self, backup_dir: str, app_name: str, keep: int = 10) -> None:
        """Remove old database backups, keeping only the most recent ones.
        
        Args:
            backup_dir: Directory containing backups
            app_name: Application name to filter backups
            keep: Number of recent backups to keep
        """
        try:
            if not os.path.exists(backup_dir):
                return
            
            # Find all backup files for this app
            backups = []
            pattern = f"{app_name}_production_"
            for filename in os.listdir(backup_dir):
                if filename.startswith(pattern) and filename.endswith(".sqlite3"):
                    backup_path = os.path.join(backup_dir, filename)
                    mtime = os.path.getmtime(backup_path)
                    backups.append((mtime, backup_path, filename))
            
            # Sort by modification time (newest first)
            backups.sort(reverse=True)
            
            # Remove old backups beyond the keep limit
            removed_count = 0
            for _mtime, backup_path, filename in backups[keep:]:
                try:
                    os.remove(backup_path)
                    removed_count += 1
                except OSError as e:
                    print(f"  ⚠ Warning: Failed to remove old backup {filename}: {e}")
            
            if removed_count > 0:
                print(f"  ℹ Removed {removed_count} old backup(s), keeping {min(len(backups), keep)} most recent")
                
        except OSError as e:
            print(f"  ⚠ Warning: Cleanup of old backups failed: {e}")
    
    def _check_pending_migrations(self, project_path: str, env_vars: str) -> bool:
        """Check if there are pending database migrations.
        
        Args:
            project_path: Path to Rails project
            env_vars: Environment variables string for rake commands
            
        Returns:
            True if migrations are pending, False otherwise
        """
        try:
            result = run(
                f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:migrate:status 2>/dev/null | grep -q ' down '",
                check=False,
                capture_output=True
            )
            return result.returncode == 0
        except Exception:
            # If we can't determine, assume migrations are needed
            return True
    
    def _is_seeds_file_idempotent(self, seeds_file: str) -> tuple[bool, str]:
        """Analyze seeds.rb to determine if it's idempotent.
        
        Args:
            seeds_file: Path to seeds.rb file
            
        Returns:
            Tuple of (is_idempotent, reason)
        """
        try:
            with open(seeds_file, 'r') as f:
                content = f.read()
            
            # Check for idempotent patterns
            idempotent_patterns = [
                'find_or_create_by',
                'find_or_initialize_by',
                'first_or_create',
                'first_or_initialize',
            ]
            
            # Check for dangerous patterns (order matters - check most destructive first)
            # Use word boundaries to avoid matching patterns within other method names
            dangerous_patterns = [
                (r'\.delete_all', 'Contains delete_all which removes data'),
                (r'\.destroy_all', 'Contains destroy_all which removes data'),
                (r'\btruncate\b', 'Contains truncate which removes data'),
                (r'\.create!', 'Uses create! which may fail on duplicates'),
                (r'\.create\(', 'Uses create which may create duplicates'),
            ]
            
            has_idempotent = any(pattern in content for pattern in idempotent_patterns)
            
            # Collect all dangerous patterns found
            found_dangerous = []
            for pattern, reason in dangerous_patterns:
                if re.search(pattern, content):
                    found_dangerous.append(reason)
            
            if found_dangerous:
                if has_idempotent:
                    reasons_str = "; ".join(found_dangerous)
                    return (False, f"Mixed: Has idempotent patterns but also: {reasons_str}")
                else:
                    return (False, found_dangerous[0])
            
            if has_idempotent:
                return (True, "Uses idempotent patterns (find_or_create_by, etc.)")
            
            # If we can't determine, assume not idempotent
            return (False, "Cannot determine if idempotent - manual review needed")
            
        except OSError:
            return (False, "Cannot read seeds file")
    
    def _get_seed_file_path(self, project_path: str, env: str = 'production') -> Optional[str]:
        """Get the appropriate seed file for the environment.
        
        Checks in order:
        1. db/seeds/{env}_seeds.rb (e.g., production_seeds.rb)
        2. db/{env}_seeds.rb
        3. db/seeds.rb (fallback)
        
        Args:
            project_path: Path to Rails project
            env: Environment name (production, development, test)
            
        Returns:
            Path to seed file if found, None otherwise
        """
        possible_paths = [
            os.path.join(project_path, "db", "seeds", f"{env}_seeds.rb"),
            os.path.join(project_path, "db", f"{env}_seeds.rb"),
            os.path.join(project_path, "db", "seeds.rb"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _get_used_ports(self) -> set[int]:
        """Get set of ports currently used by infra_tools services."""
        used_ports: set[int] = set()
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
                            match = re.search(r'-p (\d+)', content)
                            if match:
                                used_ports.add(int(match.group(1)))
                            match = re.search(r'--port (\d+)', content)
                            if match:
                                used_ports.add(int(match.group(1)))
                    except OSError:
                        pass
        except OSError:
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
                    match = re.search(r'-p (\d+)', content)
                    if match:
                        return int(match.group(1))
                    match = re.search(r'--port (\d+)', content)
                    if match:
                        return int(match.group(1))
            except OSError:
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
                           git_url: str, commit_hash: Optional[str], 
                           full_deploy: bool = True, keep_source: bool = False,
                           api_subdomain: bool = False, reset_migrations: bool = False) -> dict[str, Any]:
        dest_path = self.get_deployment_path(domain, path, git_url)
        app_name = os.path.basename(dest_path)
        persistent_root = self._get_persistent_root(app_name)
        
        if should_redeploy(dest_path, git_url, commit_hash, full_deploy):
            print(f"Deploying to {dest_path}...")
        else:
            print(f"Skipping {dest_path} (already at commit {commit_hash})...")
            
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
                'skipped': True,
                'api_subdomain': api_subdomain
            }
        
        print(f"Deploying to {dest_path}...")
        
        parent_dir = os.path.dirname(dest_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        if os.path.exists(dest_path):
            print(f"  Removing existing deployment at {dest_path}...")

            run(f"systemctl stop {shlex.quote(f'rails-{app_name}.service')}", check=False)

            if self._is_rails_project(dest_path):
                print(f"  Preserving persistent state under {persistent_root}...")
                try:
                    self._persist_rails_state_from_existing_release(dest_path, persistent_root)
                except OSError as e:
                    print(f"  ⚠ Warning: Failed to preserve persistent state: {e}")

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
        
        if project_type == "rails":
            try:
                self._link_rails_persistent_state_into_release(dest_path, persistent_root)
            except OSError as e:
                print(f"  ⚠ Warning: Failed to link persistent state: {e}")

        self.build_project(dest_path, project_type, site_root=site_root, app_name=app_name, reset_migrations=reset_migrations)

        if project_type == "rails":
            run(f"chown -R {shlex.quote(self.web_user)}:{shlex.quote(self.web_group)} {shlex.quote(persistent_root)}", check=False)
            run(f"find {shlex.quote(persistent_root)} -type d -exec chmod 775 {{}} +", check=False)
            run(f"find {shlex.quote(persistent_root)} -type f -exec chmod 664 {{}} +", check=False)

        result = run(
            f"chown -R {shlex.quote(self.web_user)}:{shlex.quote(self.web_group)} {shlex.quote(dest_path)}",
            check=False,
        )
        if result.returncode != 0:
            print(f"  ⚠ Warning: Could not set ownership to {self.web_user}:{self.web_group}")

        run(f"chmod -R 775 {shlex.quote(dest_path)}")
        
        backend_port = None
        frontend_port = None
        frontend_serve_path = None
        
        if project_type == "rails":
            service_name = f"rails-{app_name}"
            backend_port = self._get_assigned_port(service_name, 3000)
            
            cors_origins: list[str] = []
            if domain:
                cors_origins.append(f"https://{domain}")
                cors_origins.append(f"https://www.{domain}")
                cors_origins.append(f"http://{domain}")
                cors_origins.append(f"http://www.{domain}")
            
            create_rails_service(app_name, dest_path, backend_port, self.web_user, self.web_group, 
                               env_vars={"CORS_ORIGINS": ",".join(cors_origins)})
            
            frontend_path = os.path.join(dest_path, "frontend")
            if os.path.exists(frontend_path):
                print(f"  Detected frontend at {frontend_path}")
                
                api_url = "/api"
                is_root = not path or path == '/'
                
                if api_subdomain and domain:
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
                
                self._build_node_project(frontend_path, api_url, site_root)
                
                frontend_serve_path = get_project_root(frontend_path, "node")
                print(f"  Frontend will be served statically from {frontend_serve_path}")
                
                frontend_port = None
        
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
            'frontend_serve_path': frontend_serve_path,
            'api_subdomain': api_subdomain
        }
    
    def build_project(self, project_path: str, project_type: str, site_root: Optional[str] = None, app_name: Optional[str] = None, reset_migrations: bool = False):
        if project_type == "rails":
            self._build_rails_project(project_path, app_name, reset_migrations)
        elif project_type == "node":
            self._build_node_project(project_path, site_root=site_root)
        elif project_type == "static":
            self._build_static_project(project_path)
        else:
            print(f"  ⚠ Unknown project type, no build performed")
    
    def _build_rails_project(self, project_path: str, app_name: Optional[str] = None, reset_migrations: bool = False):
        print(f"  Building Rails project at {project_path}")
        
        cors_file = os.path.join(project_path, "config", "initializers", "cors.rb")
        if os.path.exists(cors_file):
            print("  Patching CORS configuration...")
            try:
                with open(cors_file, 'r') as f:
                    content = f.read()
                
                if 'ENV["CORS_ORIGINS"]' not in content:
                    new_content = content.replace(
                        'origins "http://localhost:5173", "http://127.0.0.1:5173"',
                        'origins((ENV["CORS_ORIGINS"]&.split(",") || []) + ["http://localhost:5173", "http://127.0.0.1:5173"])'
                    )
                    if new_content == content:
                         new_content = re.sub(
                            r'origins\s+["\'].*?["\'](?:,\s*["\'].*?["\'])*',
                            'origins((ENV["CORS_ORIGINS"]&.split(",") || []) + ["http://localhost:5173", "http://127.0.0.1:5173"])',
                            content
                        )

                    with open(cors_file, 'w') as f:
                        f.write(new_content)
            except OSError as e:
                print(f"  ⚠ Failed to patch CORS configuration: {e}")
        
        build_secret = secrets.token_hex(64)
        env_vars = f"RAILS_ENV=production SECRET_KEY_BASE={build_secret} TMPDIR=/var/tmp"
        
        run(f"cd {shlex.quote(project_path)} && TMPDIR=/var/tmp bundle install --deployment --without development test")
        
        print("  Setting up database...")
        
        # Check for existing database and pending migrations
        db_path = os.path.join(project_path, "db", "production.sqlite3")
        db_exists = os.path.exists(db_path) or (os.path.islink(db_path) and os.path.exists(os.path.realpath(db_path)))
        
        # Create backup before migrations if database exists and app_name is provided
        backup_created = False
        if db_exists and app_name:
            has_pending_migrations = self._check_pending_migrations(project_path, env_vars)
            if has_pending_migrations:
                print("  Pending migrations detected, creating backup before migration...")
                backup_dir = self._get_backup_dir(app_name)
                backup_path = self._backup_database(db_path, backup_dir, app_name)
                backup_created = backup_path is not None
                
                if not backup_created:
                    print("  ⚠ WARNING: Failed to create database backup before migration!")
                    print("  ⚠ Migration will proceed, but consider stopping and backing up manually.")
        
        # Create database if it doesn't exist
        run(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:create", check=False)
        
        # Run migrations or reset schema
        if reset_migrations:
            print("  Resetting database schema (--reset-migrations flag used)...")
            print("  ⚠ This will load the current schema and mark all migrations as run")
            
            # Load current schema structure
            # Note: DISABLE_DATABASE_ENVIRONMENT_CHECK=1 allows schema:load to run in production
            result = run(f"cd {shlex.quote(project_path)} && {env_vars} DISABLE_DATABASE_ENVIRONMENT_CHECK=1 bundle exec rake db:schema:load", capture_output=True)
            if result.returncode != 0:
                print(f"  ✗ Schema load failed with exit code {result.returncode}")
                if result.stderr:
                    print(f"  Error: {result.stderr}")
                if backup_created and app_name:
                    print(f"  ℹ Database backup is available in: {self._get_backup_dir(app_name)}")
                raise RuntimeError(f"Database schema:load failed with exit code {result.returncode}")
            
            print("  ✓ Schema loaded successfully")
            
            # Run any migrations that are newer than the schema
            print("  Running any new migrations...")
            result = run(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:migrate", capture_output=True)
            if result.returncode != 0:
                print(f"  ✗ Migration failed with exit code {result.returncode}")
                if result.stderr:
                    print(f"  Error: {result.stderr}")
                if backup_created and app_name:
                    print(f"  ℹ Database backup is available in: {self._get_backup_dir(app_name)}")
                raise RuntimeError(f"Database migration failed with exit code {result.returncode}")
            
            print("  ✓ Migrations completed successfully")
        else:
            # Normal migration path
            print("  Running database migrations...")
            result = run(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:migrate", capture_output=True)
            
            if result.returncode != 0:
                error_output = result.stderr if result.stderr else result.stdout
                
                # Check for common migration errors that indicate schema reset is needed
                if error_output and any(indicator in error_output.lower() for indicator in [
                    'already exists',
                    'duplicate column',
                    'table already exists',
                    'column already exists'
                ]):
                    print(f"  ✗ Migration failed: Schema conflict detected")
                    print(f"\n  This typically happens when:")
                    print(f"    • Migrations were squashed or reset in the repository")
                    print(f"    • The database schema is out of sync with migration history")
                    print(f"\n  To fix this, redeploy with the --reset-migrations flag:")
                    print(f"    ./setup_server_web.py <host> --deploy <deploy-spec> <git-url> --reset-migrations")
                    print(f"\n  ⚠ WARNING: --reset-migrations will:")
                    print(f"    • Load the current schema from db/schema.rb")
                    print(f"    • Mark all migrations as already run")
                    print(f"    • Preserve your data (tables won't be dropped)")
                    print(f"\n  Error details:")
                    print(f"  {error_output[:500]}")
                else:
                    print(f"  ✗ Migration failed with exit code {result.returncode}")
                    if error_output:
                        print(f"  Error: {error_output[:500]}")
                
                if backup_created and app_name:
                    print(f"\n  ℹ Database backup is available in: {self._get_backup_dir(app_name)}")
                
                raise RuntimeError(f"Database migration failed with exit code {result.returncode}")
            
            print("  ✓ Migrations completed successfully")
        
        # Handle database seeding intelligently
        seeds_file = self._get_seed_file_path(project_path, 'production')
        
        if seeds_file:
            # Determine which seed file is being used
            seed_type = "standard"
            if "production_seeds.rb" in seeds_file:
                seed_type = "production-specific"
            
            # Check if seeds are idempotent
            is_idempotent, reason = self._is_seeds_file_idempotent(seeds_file)
            
            if not db_exists:
                # New database - always safe to seed
                print(f"  New database detected, running {seed_type} seeds...")
                if "seeds.rb" != os.path.basename(seeds_file):
                    # Custom seed file - need to load it explicitly
                    seed_cmd = f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rails runner {shlex.quote(seeds_file)}"
                else:
                    seed_cmd = f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:seed"
                
                seed_result = run(seed_cmd, capture_output=True)
                if seed_result.stdout:
                    print(seed_result.stdout)
            else:
                # Existing database - check if seeds are safe
                if is_idempotent:
                    print(f"  ✓ Running {seed_type} seeds (idempotent - safe for existing database)")
                    print(f"    Reason: {reason}")
                    
                    if "seeds.rb" != os.path.basename(seeds_file):
                        seed_cmd = f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rails runner {shlex.quote(seeds_file)}"
                    else:
                        seed_cmd = f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake db:seed"
                    
                    seed_result = run(seed_cmd, capture_output=True)
                    if seed_result.stdout:
                        print(seed_result.stdout)
                else:
                    # Not idempotent - skip with warning
                    print(f"  ⚠ Skipping {seed_type} seeds (existing database - seeds may not be idempotent)")
                    print(f"    Reason: {reason}")
                    print("  ℹ To run seeds manually if safe:")
                    if "seeds.rb" != os.path.basename(seeds_file):
                        print(f"    cd {project_path} && {env_vars} bundle exec rails runner {seeds_file}")
                    else:
                        print(f"    cd {project_path} && {env_vars} bundle exec rake db:seed")
        else:
            # Check for environment-specific alternatives
            alt_paths = [
                os.path.join(project_path, "db", "seeds", "production_seeds.rb"),
                os.path.join(project_path, "db", "production_seeds.rb"),
            ]
            
            for alt_path in alt_paths:
                if os.path.exists(alt_path):
                    print(f"  ℹ Found alternative seed file: {os.path.relpath(alt_path, project_path)}")
                    print("    Not loaded automatically. Create db/seeds.rb to use it.")
                    break
        
        check_task = run(f"cd {shlex.quote(project_path)} && bundle exec rake -T assets:precompile | grep assets:precompile", check=False, capture_output=True)
        if check_task.returncode == 0:
            run(f"cd {shlex.quote(project_path)} && {env_vars} bundle exec rake assets:precompile")
        else:
            print("  ℹ Skipping assets:precompile (task not found, likely API-only app)")
        
        print("  ✓ Rails project built")
    
    def _build_node_project(self, project_path: str, api_url: Optional[str] = None, site_root: Optional[str] = None):
        print(f"  Building Node.js project at {project_path}")
        
        run(f"cd {shlex.quote(project_path)} && TMPDIR=/var/tmp npm install")
        
        build_cmd = "npm run build"
        env_prefix = ["TMPDIR=/var/tmp"]

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
        
        result = run(f"cd {shlex.quote(project_path)} && {build_cmd}", check=False)
        
        if result.returncode != 0:
            print("  ⚠ npm run build failed or not configured, skipping build step")
        else:
            print("  ✓ Node.js project built")
    
    def _build_static_project(self, project_path: str):
        print(f"  Static website at {project_path} - no build required")
        print("  ✓ Static files ready")

