#!/usr/bin/env python3
"""
CI/CD Executor

Processes CI/CD jobs triggered by the webhook receiver.
Clones repositories, runs build/test/deploy scripts, and reports status.
Supports both local deployment and remote deployment to app servers.

Logs to: /var/log/infra_tools/web/cicd_executor.log
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
import shlex
import time
import fcntl
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification

logger = get_service_logger('cicd_executor', 'web', use_syslog=True)

CONFIG_DIR = "/etc/infra_tools/cicd"
CONFIG_FILE = os.path.join(CONFIG_DIR, "webhook_config.json")
STATE_DIR = "/var/lib/infra_tools/cicd"
JOBS_DIR = os.path.join(STATE_DIR, "jobs")
WORKSPACES_DIR = os.path.join(STATE_DIR, "workspaces")
LOGS_DIR = os.path.join(STATE_DIR, "logs")
LOCK_FILE = os.path.join(STATE_DIR, "executor.lock")


def load_config() -> dict:
    """Load webhook configuration from JSON file."""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Configuration file not found: {CONFIG_FILE}")
        return {}
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return {}


def get_repo_workspace(repo_url: str) -> str:
    """Get workspace directory for a repository."""
    # Extract repo name from URL
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
    workspace = os.path.join(WORKSPACES_DIR, repo_name)
    return workspace


def clone_or_update_repo(repo_url: str, workspace: str, ref: str) -> bool:
    """Clone repository if it doesn't exist, or pull latest changes."""
    try:
        if not os.path.exists(workspace):
            logger.info(f"Cloning repository: {repo_url}")
            result = subprocess.run(
                ['git', 'clone', repo_url, workspace],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                logger.error(f"Failed to clone repository: {result.stderr}")
                return False
        
        logger.info(f"Fetching latest changes from {repo_url}")
        result = subprocess.run(
            ['git', 'fetch', '--all'],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            logger.error(f"Failed to fetch: {result.stderr}")
            return False
        
        result = subprocess.run(
            ['git', 'reset', '--hard', 'HEAD'],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            logger.error(f"Failed to reset: {result.stderr}")
            return False
        
        result = subprocess.run(
            ['git', 'clean', '-fd'],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            logger.warning(f"git clean had issues: {result.stderr}")
        
        branch = ref.replace('refs/heads/', '')
        logger.info(f"Checking out: {branch}")
        result = subprocess.run(
            ['git', 'checkout', branch],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            logger.error(f"Failed to checkout {branch}: {result.stderr}")
            return False
        
        result = subprocess.run(
            ['git', 'pull', '--ff-only'],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            logger.error(f"Failed to pull: {result.stderr}")
            return False
        
        logger.info(f"Repository updated successfully")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("Git operation timed out")
        return False
    except Exception as e:
        logger.error(f"Failed to clone/update repository: {e}")
        return False


def run_script(script_path: str, workspace: str, log_file: str) -> bool:
    """Run a CI/CD script and log output."""
    # Resolve relative paths against workspace
    if not os.path.isabs(script_path):
        script_path = os.path.join(workspace, script_path)
    
    if not os.path.exists(script_path):
        logger.error(f"Script not found: {script_path}")
        return False
    
    try:
        logger.info(f"Running script: {script_path}")
        
        with open(log_file, 'a') as log:
            log.write(f"\n{'='*80}\n")
            log.write(f"Running: {script_path}\n")
            log.write(f"{'='*80}\n\n")
            
            result = subprocess.run(
                ['/bin/bash', script_path],
                cwd=workspace,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=3600  # 1 hour timeout
            )
            
            log.write(f"\n{'='*80}\n")
            log.write(f"Exit code: {result.returncode}\n")
            log.write(f"{'='*80}\n")
        
        if result.returncode == 0:
            logger.info(f"Script completed successfully: {script_path}")
            return True
        else:
            logger.error(f"Script failed with exit code {result.returncode}: {script_path}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Script timed out: {script_path}")
        return False
    except Exception as e:
        logger.error(f"Failed to run script: {e}")
        return False


def process_job(job_file: str) -> bool:
    """Process a single CI/CD job."""
    logger.info(f"Processing job: {job_file}")
    
    try:
        with open(job_file, 'r') as f:
            job_data = json.load(f)
        
        repo_url = job_data.get('repo_url')
        ref = job_data.get('ref')
        commit_sha = job_data.get('commit_sha')
        pusher = job_data.get('pusher', 'unknown')
        
        if not repo_url or not ref or not commit_sha:
            logger.error("Invalid job data")
            return False
        
        config = load_config()
        repos = config.get('repositories', [])
        
        repo_config = None
        for repo in repos:
            if repo.get('url') == repo_url:
                repo_config = repo
                break
        
        if not repo_config:
            logger.error(f"Repository not configured: {repo_url}")
            return False
        
        workspace = get_repo_workspace(repo_url)
        os.makedirs(workspace, exist_ok=True)
        
        log_file = os.path.join(LOGS_DIR, f"{commit_sha[:8]}.log")
        os.makedirs(LOGS_DIR, exist_ok=True)
        
        with open(log_file, 'w') as log:
            log.write(f"CI/CD Build Log\n")
            log.write(f"{'='*80}\n")
            log.write(f"Repository: {repo_url}\n")
            log.write(f"Branch: {ref}\n")
            log.write(f"Commit: {commit_sha}\n")
            log.write(f"Pusher: {pusher}\n")
            log.write(f"Timestamp: {job_data.get('timestamp', 'unknown')}\n")
            deploy_target = repo_config.get('deploy_target')
            if deploy_target:
                log.write(f"Deploy Target: {deploy_target}\n")
            log.write(f"{'='*80}\n\n")
        
        if not clone_or_update_repo(repo_url, workspace, ref):
            logger.error("Failed to clone/update repository")
            notify_failure(repo_url, commit_sha, "Failed to clone/update repository")
            return False
        
        scripts = repo_config.get('scripts', {})
        success = True
        
        for script_name in ['install', 'build', 'test']:
            script_path = scripts.get(script_name)
            if script_path:
                if not run_script(script_path, workspace, log_file):
                    logger.error(f"Failed at stage: {script_name}")
                    success = False
                    break
        
        if success:
            deploy_target = repo_config.get('deploy_target')
            deploy_spec = repo_config.get('deploy_spec')
            
            if deploy_target:
                success = perform_remote_deployment(
                    workspace, deploy_target, deploy_spec, repo_url, 
                    commit_sha, log_file, repo_config
                )
            else:
                deploy_script = scripts.get('deploy')
                if deploy_script:
                    if not run_script(deploy_script, workspace, log_file):
                        logger.error("Failed at stage: deploy")
                        success = False
        
        notification_configs = load_notification_configs_from_state(logger)
        if notification_configs:
            if success:
                notify_success(repo_url, commit_sha, log_file, notification_configs)
            else:
                notify_failure(repo_url, commit_sha, "Build failed", notification_configs)
        
        os.remove(job_file)
        
        logger.info(f"Job completed: {job_file} - {'SUCCESS' if success else 'FAILED'}")
        return success
        
    except Exception as e:
        logger.error(f"Error processing job: {e}")
        return False


def perform_remote_deployment(
    workspace: str,
    deploy_target: str,
    deploy_spec: Optional[str],
    repo_url: str,
    commit_sha: str,
    log_file: str,
    repo_config: dict
) -> bool:
    """Deploy built artifacts to a remote app server."""
    from lib.remote_deploy import (
        get_deploy_target,
        push_artifact,
        push_nginx_config,
        reload_nginx,
        restart_service,
    )
    from lib.deploy_utils import parse_deploy_spec, detect_project_type, get_project_root
    from lib.nginx_config import generate_merged_nginx_config
    
    target = get_deploy_target(deploy_target)
    if not target:
        logger.error(f"Unknown deploy target: {deploy_target}")
        with open(log_file, 'a') as log:
            log.write(f"\n✗ Unknown deploy target: {deploy_target}\n")
        return False
    
    domain = None
    path = '/'
    if deploy_spec:
        domain, path = parse_deploy_spec(deploy_spec)
    
    project_type = detect_project_type(workspace)
    logger.info(f"Detected project type: {project_type}")
    
    serve_path = get_project_root(workspace, project_type)
    base_dir = target.get('base_dir', '/var/www')
    
    from lib.deploy_utils import create_safe_directory_name
    dir_name = create_safe_directory_name(domain, path)
    remote_path = f"{base_dir}/{dir_name}" if dir_name else base_dir
    
    with open(log_file, 'a') as log:
        log.write(f"\n{'='*80}\n")
        log.write(f"Deploying to remote server: {deploy_target}\n")
        log.write(f"Remote path: {remote_path}\n")
        log.write(f"{'='*80}\n\n")
    
    exclude_patterns = ['.git', 'node_modules', '__pycache__', '*.log']
    
    if not push_artifact(serve_path, deploy_target, remote_path, exclude_patterns):
        logger.error("Failed to push artifact to remote server")
        with open(log_file, 'a') as log:
            log.write("✗ Failed to push artifact\n")
        return False
    
    with open(log_file, 'a') as log:
        log.write(f"✓ Artifact pushed to {deploy_target}:{remote_path}\n")
    
    if domain:
        deployment = {
            'path': path,
            'serve_path': remote_path,
            'project_type': project_type,
            'needs_proxy': project_type == 'rails',
            'domain': domain,
        }
        
        nginx_config = generate_merged_nginx_config(domain, [deployment])
        
        if not push_nginx_config(nginx_config, deploy_target, domain):
            logger.error("Failed to push nginx config")
            with open(log_file, 'a') as log:
                log.write("✗ Failed to push nginx config\n")
            return False
        
        with open(log_file, 'a') as log:
            log.write(f"✓ Nginx config pushed for {domain}\n")
        
        if not reload_nginx(deploy_target):
            logger.error("Failed to reload nginx on remote server")
            with open(log_file, 'a') as log:
                log.write("✗ Failed to reload nginx\n")
            return False
        
        with open(log_file, 'a') as log:
            log.write("✓ Nginx reloaded\n")
    
    deploy_script = repo_config.get('scripts', {}).get('deploy')
    if deploy_script:
        from lib.remote_deploy import _build_ssh_cmd
        target_config = get_deploy_target(deploy_target)
        
        if not target_config:
            logger.error(f"Deploy target not found: {deploy_target}")
            return False
        
        script_path = deploy_script if os.path.isabs(deploy_script) else os.path.join(workspace, deploy_script)
        
        if not os.path.exists(script_path):
            logger.warning(f"Deploy script configured but not found: {script_path}")
            with open(log_file, 'a') as log:
                log.write(f"\n⚠ Deploy script not found: {script_path}\n")
        else:
            with open(script_path, 'r') as f:
                script_content = f.read()
            
            remote_cmd = f"cd {remote_path} && bash -c {shlex.quote(script_content)}"
            ssh_cmd = _build_ssh_cmd(target_config, remote_cmd)
            
            try:
                result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=300)
                with open(log_file, 'a') as log:
                    log.write(f"\nDeploy script output:\n{result.stdout}\n")
                    if result.stderr:
                        log.write(f"Errors:\n{result.stderr}\n")
                
                if result.returncode != 0:
                    logger.error(f"Deploy script failed: {result.stderr}")
                    return False
            except Exception as e:
                logger.error(f"Failed to run deploy script: {e}")
                return False
    
    logger.info(f"Remote deployment to {deploy_target} completed")
    return True


def notify_success(repo_url: str, commit_sha: str, log_file: str, notification_configs: list) -> None:
    """Send success notification."""
    try:
        send_notification(
            notification_configs,
            subject=f"CI/CD Success: {repo_url}",
            job="cicd_executor",
            status="good",
            message=f"Build succeeded for commit {commit_sha[:8]}\nLog: {log_file}",
            logger=logger
        )
    except Exception as e:
        logger.warning(f"Failed to send success notification: {e}")


def notify_failure(repo_url: str, commit_sha: str, reason: str, notification_configs: Optional[list] = None) -> None:
    """Send failure notification."""
    if not notification_configs:
        notification_configs = load_notification_configs_from_state(logger)
    
    if notification_configs:
        try:
            send_notification(
                notification_configs,
                subject=f"CI/CD Failed: {repo_url}",
                job="cicd_executor",
                status="error",
                message=f"Build failed for commit {commit_sha[:8]}\nReason: {reason}",
                logger=logger
            )
        except Exception as e:
            logger.warning(f"Failed to send failure notification: {e}")


def main():
    """Main function to process CI/CD jobs."""
    logger.info("Starting CI/CD executor")
    
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    lock_fd = None
    try:
        lock_fd = open(LOCK_FILE, 'w')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            logger.info("Another executor instance is running, exiting")
            return 0
        
        job_files = sorted(Path(JOBS_DIR).glob('*.json'))
        
        if not job_files:
            logger.info("No pending jobs")
            return 0
        
        logger.info(f"Found {len(job_files)} pending job(s)")
        
        success_count = 0
        failure_count = 0
        
        for job_file in job_files:
            if process_job(str(job_file)):
                success_count += 1
            else:
                failure_count += 1
        
        logger.info(f"CI/CD executor finished: {success_count} successful, {failure_count} failed")
        
        return 0 if failure_count == 0 else 1
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
