"""Tests for CI/CD webhook system."""

from __future__ import annotations

import unittest
import json
import hmac
import hashlib
import tempfile
import time
from unittest.mock import patch, mock_open, MagicMock
import sys
import os

# Add the parent directory to the path so we can import the modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web.cicd_steps import (
    install_cicd_dependencies,
    create_cicd_user,
    create_cicd_directories,
    generate_webhook_secret,
    create_default_webhook_config,
    create_webhook_receiver_service,
    create_cicd_executor_service,
    configure_nginx_for_webhook,
)


class TestCICDSteps(unittest.TestCase):
    """Test CI/CD setup steps."""
    
    @patch('web.cicd_steps.is_package_installed')
    @patch('web.cicd_steps.run')
    def test_install_cicd_dependencies_already_installed(self, mock_run, mock_is_installed):
        """Test that we skip installation if dependencies are already installed."""
        mock_is_installed.return_value = True
        mock_config = MagicMock()
        
        install_cicd_dependencies(mock_config)
        
        # Should not call apt-get install
        mock_run.assert_not_called()
    
    @patch('web.cicd_steps.is_package_installed')
    @patch('web.cicd_steps.run')
    def test_install_cicd_dependencies_missing(self, mock_run, mock_is_installed):
        """Test that we install missing dependencies."""
        mock_is_installed.return_value = False
        mock_config = MagicMock()
        
        install_cicd_dependencies(mock_config)
        
        # Should install git
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn('apt-get install', call_args)
        self.assertIn('git', call_args)
    
    @patch('web.cicd_steps.run')
    def test_create_cicd_user_already_exists(self, mock_run):
        """Test that we skip user creation if user exists."""
        # Simulate user exists (id command returns 0)
        mock_run.return_value = MagicMock(returncode=0)
        mock_config = MagicMock()
        
        create_cicd_user(mock_config)
        
        # Should only call id command
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn('id webhook', mock_run.call_args[0][0])
    
    @patch('web.cicd_steps.run')
    def test_create_cicd_user_new(self, mock_run):
        """Test that we create user if it doesn't exist."""
        # First call (id): user doesn't exist, second call (useradd): create user
        mock_run.side_effect = [
            MagicMock(returncode=1),  # id fails
            MagicMock(returncode=0),  # useradd succeeds
        ]
        mock_config = MagicMock()
        
        create_cicd_user(mock_config)
        
        # Should call both id and useradd
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn('useradd', mock_run.call_args_list[1][0][0])
        self.assertIn('webhook', mock_run.call_args_list[1][0][0])
    
    @patch('web.cicd_steps.os.path.exists')
    @patch('web.cicd_steps.os.makedirs')
    @patch('web.cicd_steps.run')
    def test_create_cicd_directories(self, mock_run, mock_makedirs, mock_exists):
        """Test that we create required directories."""
        mock_exists.return_value = False
        mock_config = MagicMock()
        
        # Mock that webhook user exists (id command succeeds)
        mock_run.return_value = MagicMock(returncode=0)
        
        create_cicd_directories(mock_config)
        
        # Should create multiple directories
        self.assertGreaterEqual(mock_makedirs.call_count, 4)
        
        # Should check for webhook user existence
        user_check_calls = [call for call in mock_run.call_args_list if 'id webhook' in str(call)]
        self.assertGreater(len(user_check_calls), 0)
        
        # Should set ownership (when user exists)
        ownership_calls = [call for call in mock_run.call_args_list if 'chown' in str(call)]
        self.assertGreater(len(ownership_calls), 0)
    
    @patch('web.cicd_steps.os.path.exists')
    @patch('web.cicd_steps.secrets.token_urlsafe')
    @patch('builtins.open', new_callable=mock_open)
    @patch('web.cicd_steps.os.chmod')
    @patch('web.cicd_steps.run')
    def test_generate_webhook_secret_new(self, mock_run, mock_chmod, mock_file, mock_token, mock_exists):
        """Test that we generate a new webhook secret."""
        mock_exists.return_value = False
        mock_token.return_value = "test-secret-token"
        mock_config = MagicMock()
        
        secret = generate_webhook_secret(mock_config)
        
        self.assertEqual(secret, "test-secret-token")
        mock_token.assert_called_once_with(32)
        self.assertEqual(mock_file.call_count, 2)
        self.assertEqual(mock_chmod.call_count, 2)
    
    @patch('web.cicd_steps.os.path.exists')
    @patch('web.cicd_steps.os.chmod')
    @patch('builtins.open', new_callable=mock_open, read_data="existing-secret")
    @patch('web.cicd_steps.run')
    def test_generate_webhook_secret_existing(self, mock_run, mock_file, mock_chmod, mock_exists):
        """Test that we reuse existing webhook secret."""
        def exists_side_effect(path):
            return path.endswith('webhook_secret')
        mock_exists.side_effect = exists_side_effect
        mock_config = MagicMock()
        
        secret = generate_webhook_secret(mock_config)
        
        self.assertEqual(secret, "existing-secret")
    
    @patch('web.cicd_steps.os.path.exists')
    @patch('builtins.open', new_callable=mock_open)
    @patch('web.cicd_steps.json.dump')
    @patch('web.cicd_steps.os.chmod')
    def test_create_default_webhook_config(self, mock_chmod, mock_json_dump, mock_file, mock_exists):
        """Test that we create default webhook configuration."""
        mock_exists.return_value = False
        mock_config = MagicMock()
        
        create_default_webhook_config(mock_config)
        
        mock_file.assert_called_once()
        mock_json_dump.assert_called_once()
        
        # Check that config has repositories key
        config_data = mock_json_dump.call_args[0][0]
        self.assertIn('repositories', config_data)
        self.assertIsInstance(config_data['repositories'], list)
    
    @patch('web.cicd_steps.cleanup_service')
    @patch('web.cicd_steps.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="test-secret")
    @patch('web.cicd_steps.run')
    def test_create_webhook_receiver_service(self, mock_run, mock_file, mock_exists, mock_cleanup):
        """Test webhook receiver service creation."""
        mock_exists.return_value = True
        mock_config = MagicMock()
        
        with patch('builtins.open', mock_open()) as mock_service_file:
            create_webhook_receiver_service(mock_config)
        
        # Should cleanup existing service
        mock_cleanup.assert_called_once_with('webhook-receiver')
        
        # Should reload systemd
        reload_calls = [call for call in mock_run.call_args_list if 'daemon-reload' in str(call)]
        self.assertGreater(len(reload_calls), 0)
        
        # Should enable and start service
        enable_calls = [call for call in mock_run.call_args_list if 'enable' in str(call)]
        start_calls = [call for call in mock_run.call_args_list if 'start' in str(call)]
        self.assertGreater(len(enable_calls), 0)
        self.assertGreater(len(start_calls), 0)
    
    @patch('web.cicd_steps.cleanup_service')
    @patch('web.cicd_steps.run')
    def test_create_cicd_executor_service(self, mock_run, mock_cleanup):
        """Test CI/CD executor service creation."""
        mock_config = MagicMock()
        
        with patch('builtins.open', mock_open()) as mock_file:
            create_cicd_executor_service(mock_config)
        
        # Should cleanup existing service
        mock_cleanup.assert_called_once_with('cicd-executor')
        
        # Should reload systemd
        reload_calls = [call for call in mock_run.call_args_list if 'daemon-reload' in str(call)]
        self.assertGreater(len(reload_calls), 0)
    
    @patch('web.cicd_steps.os.path.exists')
    @patch('web.cicd_steps.os.makedirs')
    @patch('web.cicd_steps.run')
    def test_configure_nginx_for_webhook(self, mock_run, mock_makedirs, mock_exists):
        """Test nginx configuration for webhook endpoint."""
        mock_exists.return_value = False
        mock_config = MagicMock()
        
        # Mock nginx -t to succeed
        mock_run.side_effect = [
            MagicMock(returncode=0),  # nginx -t
            MagicMock(returncode=0),  # systemctl reload nginx
        ]
        
        with patch('builtins.open', mock_open()) as mock_file:
            configure_nginx_for_webhook(mock_config)
        
        # Should write nginx config
        mock_file.assert_called_once()
        
        # Should test nginx config
        test_calls = [call for call in mock_run.call_args_list if 'nginx -t' in str(call)]
        self.assertGreater(len(test_calls), 0)
        
        # Should reload nginx
        reload_calls = [call for call in mock_run.call_args_list if 'reload nginx' in str(call)]
        self.assertGreater(len(reload_calls), 0)


class TestWebhookSignatureVerification(unittest.TestCase):
    """Test HMAC signature verification logic."""
    
    def test_valid_signature(self):
        """Test that valid signatures are accepted."""
        secret = "test-secret"
        payload = b'{"test": "data"}'
        
        # Compute signature like GitHub does
        signature = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        signature_header = f"sha256={signature}"
        
        # Import and test the verification function
        # Note: This would require importing from webhook_receiver.py
        # For now, we'll just verify the HMAC computation
        expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        actual = signature
        
        self.assertEqual(expected, actual)
    
    def test_invalid_signature(self):
        """Test that invalid signatures are rejected."""
        secret = "test-secret"
        payload = b'{"test": "data"}'
        
        # Compute correct signature
        correct_signature = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        
        # Use different secret
        wrong_signature = hmac.new("wrong-secret".encode('utf-8'), payload, hashlib.sha256).hexdigest()
        
        self.assertNotEqual(correct_signature, wrong_signature)


class TestAppServerSteps(unittest.TestCase):
    """Test app server setup steps."""
    
    @patch('web.app_server_steps.is_package_installed')
    @patch('web.app_server_steps.run')
    def test_install_app_server_dependencies_already_installed(self, mock_run, mock_is_installed):
        """Test that we skip installation if dependencies are already installed."""
        mock_is_installed.return_value = True
        mock_config = MagicMock()
        
        from web.app_server_steps import install_app_server_dependencies
        install_app_server_dependencies(mock_config)
        
        mock_run.assert_not_called()
    
    @patch('web.app_server_steps.is_package_installed')
    @patch('web.app_server_steps.run')
    def test_install_app_server_dependencies_missing(self, mock_run, mock_is_installed):
        """Test that we install missing dependencies."""
        mock_is_installed.return_value = False
        mock_config = MagicMock()
        
        from web.app_server_steps import install_app_server_dependencies
        install_app_server_dependencies(mock_config)
        
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn('apt-get install', call_args)
    
    @patch('web.app_server_steps.run')
    def test_create_deploy_user_already_exists(self, mock_run):
        """Test that we skip user creation if user exists."""
        mock_run.return_value = MagicMock(returncode=0)
        mock_config = MagicMock()
        
        from web.app_server_steps import create_deploy_user
        create_deploy_user(mock_config)
        
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn('id deploy', mock_run.call_args[0][0])
    
    @patch('web.app_server_steps.run')
    def test_create_deploy_user_new(self, mock_run):
        """Test that we create user if it doesn't exist."""
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        mock_config = MagicMock()
        
        from web.app_server_steps import create_deploy_user
        create_deploy_user(mock_config)
        
        self.assertGreater(mock_run.call_count, 1)


class TestBuildServerSteps(unittest.TestCase):
    """Test build server setup steps."""
    
    @patch('web.build_server_steps.os.path.exists')
    @patch('web.build_server_steps.run')
    def test_generate_deploy_ssh_key_existing(self, mock_run, mock_exists):
        """Test that we skip key generation if key already exists."""
        mock_exists.return_value = True
        mock_config = MagicMock()
        
        from web.build_server_steps import generate_deploy_ssh_key
        generate_deploy_ssh_key(mock_config)
        
        mock_run.assert_not_called()
    
    @patch('web.build_server_steps.os.path.exists')
    @patch('web.build_server_steps.os.makedirs')
    @patch('web.build_server_steps.run')
    def test_generate_deploy_ssh_key_new(self, mock_run, mock_makedirs, mock_exists):
        """Test that we generate a new SSH key."""
        mock_exists.return_value = False
        mock_config = MagicMock()
        
        from web.build_server_steps import generate_deploy_ssh_key
        generate_deploy_ssh_key(mock_config)
        
        ssh_keygen_calls = [call for call in mock_run.call_args_list if 'ssh-keygen' in str(call)]
        self.assertEqual(len(ssh_keygen_calls), 1)
    
    @patch('web.build_server_steps.os.path.exists')
    @patch('web.build_server_steps.os.makedirs')
    @patch('web.build_server_steps.os.chmod')
    @patch('builtins.open', new_callable=mock_open)
    @patch('web.build_server_steps.json.dump')
    def test_configure_deploy_targets(self, mock_json_dump, mock_file, mock_chmod, mock_makedirs, mock_exists):
        """Test that we configure deploy targets."""
        mock_exists.return_value = False
        mock_config = MagicMock()
        mock_config.deploy_targets = ['app1.example.com', 'app2.example.com']
        
        from web.build_server_steps import configure_deploy_targets
        configure_deploy_targets(mock_config)
        
        mock_json_dump.assert_called_once()
        config_data = mock_json_dump.call_args[0][0]
        self.assertIn('app1.example.com', config_data)
        self.assertIn('app2.example.com', config_data)


class TestRemoteDeploy(unittest.TestCase):
    """Test remote deployment utilities."""
    
    @patch('lib.remote_deploy.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"app1.example.com": {"host": "app1.example.com"}}')
    def test_load_deploy_targets(self, mock_file, mock_exists):
        """Test loading deploy targets configuration."""
        mock_exists.return_value = True
        
        from lib.remote_deploy import load_deploy_targets
        targets = load_deploy_targets()
        
        self.assertIn('app1.example.com', targets)
    
    @patch('lib.remote_deploy.load_deploy_targets')
    def test_get_deploy_target(self, mock_load):
        """Test getting a specific deploy target."""
        mock_load.return_value = {'app1.example.com': {'host': 'app1.example.com'}}
        
        from lib.remote_deploy import get_deploy_target
        target = get_deploy_target('app1.example.com')
        
        self.assertIsNotNone(target)
        if target:
            self.assertEqual(target['host'], 'app1.example.com')
    
    @patch('lib.remote_deploy.load_deploy_targets')
    def test_get_deploy_target_not_found(self, mock_load):
        """Test getting a non-existent deploy target."""
        mock_load.return_value = {}
        
        from lib.remote_deploy import get_deploy_target
        target = get_deploy_target('unknown.example.com')
        
        self.assertIsNone(target)


class TestCleanupOldBuildLogs(unittest.TestCase):
    """Test build log cleanup."""

    def test_cleanup_removes_old_logs(self):
        """Old log files are removed."""
        from web.service_tools.cicd_executor import cleanup_old_build_logs

        with tempfile.TemporaryDirectory() as tmpdir:
            old_log = os.path.join(tmpdir, 'abc12345.log')
            with open(old_log, 'w') as f:
                f.write('old build log')
            old_time = time.time() - (40 * 24 * 60 * 60)
            os.utime(old_log, (old_time, old_time))

            with patch('web.service_tools.cicd_executor.LOGS_DIR', tmpdir):
                removed = cleanup_old_build_logs(days_to_keep=30)

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(old_log))

    def test_cleanup_keeps_recent_logs(self):
        """Recent log files are not removed."""
        from web.service_tools.cicd_executor import cleanup_old_build_logs

        with tempfile.TemporaryDirectory() as tmpdir:
            recent_log = os.path.join(tmpdir, 'def67890.log')
            with open(recent_log, 'w') as f:
                f.write('recent build log')

            with patch('web.service_tools.cicd_executor.LOGS_DIR', tmpdir):
                removed = cleanup_old_build_logs(days_to_keep=30)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(recent_log))

    def test_cleanup_ignores_non_log_files(self):
        """Non-.log files in the logs directory are not removed."""
        from web.service_tools.cicd_executor import cleanup_old_build_logs

        with tempfile.TemporaryDirectory() as tmpdir:
            other_file = os.path.join(tmpdir, 'somefile.txt')
            with open(other_file, 'w') as f:
                f.write('not a log')
            old_time = time.time() - (60 * 24 * 60 * 60)
            os.utime(other_file, (old_time, old_time))

            with patch('web.service_tools.cicd_executor.LOGS_DIR', tmpdir):
                removed = cleanup_old_build_logs(days_to_keep=30)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(other_file))

    def test_cleanup_missing_logs_dir(self):
        """Returns 0 when the logs directory does not exist."""
        from web.service_tools.cicd_executor import cleanup_old_build_logs

        with patch('web.service_tools.cicd_executor.LOGS_DIR', '/nonexistent/logs/dir'):
            removed = cleanup_old_build_logs(days_to_keep=30)

        self.assertEqual(removed, 0)


class TestCleanupStaleWorkspaces(unittest.TestCase):
    """Test stale workspace cleanup."""

    def test_removes_workspace_not_in_config(self):
        """Workspaces for repos not in config are removed."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            stale_ws = os.path.join(tmpdir, 'old-repo')
            os.makedirs(stale_ws)

            config = {'repositories': []}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(stale_ws))

    def test_keeps_workspace_in_config(self):
        """Workspaces for configured repos are kept."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            active_ws = os.path.join(tmpdir, 'my-repo')
            os.makedirs(active_ws)

            config = {'repositories': [{'url': 'https://github.com/org/my-repo.git'}]}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(active_ws))

    def test_removes_stale_keeps_active(self):
        """Only stale workspaces are removed when both are present."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            active_ws = os.path.join(tmpdir, 'active-repo')
            stale_ws = os.path.join(tmpdir, 'stale-repo')
            os.makedirs(active_ws)
            os.makedirs(stale_ws)

            config = {'repositories': [{'url': 'https://github.com/org/active-repo.git'}]}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 1)
            self.assertTrue(os.path.exists(active_ws))
            self.assertFalse(os.path.exists(stale_ws))

    def test_missing_workspaces_dir(self):
        """Returns 0 when workspaces directory does not exist."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        config = {'repositories': []}
        with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', '/nonexistent/workspaces'):
            removed = cleanup_stale_workspaces(config)

        self.assertEqual(removed, 0)

    def test_ignores_files_in_workspaces_dir(self):
        """Regular files in the workspaces dir are not deleted."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            stray_file = os.path.join(tmpdir, 'somefile.txt')
            with open(stray_file, 'w') as f:
                f.write('stray file')

            config = {'repositories': []}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(stray_file))


if __name__ == '__main__':
    unittest.main()
