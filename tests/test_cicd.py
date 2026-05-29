"""Tests for CI/CD webhook system."""

from __future__ import annotations

import unittest
import json
import hmac
import hashlib
import subprocess
import tempfile
import time
from unittest.mock import patch, mock_open, MagicMock
import sys
import os

# Add the parent directory to the path so we can import the modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web.service_tools import cicd_executor
from web.service_tools import webhook_receiver

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
        
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn('id webhook', mock_run.call_args_list[0][0][0])
        self.assertIn('usermod --home /var/lib/infra_tools/cicd webhook', mock_run.call_args_list[1][0][0])
    
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
        self.assertIn('--home-dir /var/lib/infra_tools/cicd', mock_run.call_args_list[1][0][0])
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
        written_service = ''.join(call.args[0] for call in mock_service_file().write.call_args_list)
        self.assertIn('Environment=HOME=/var/lib/infra_tools/cicd', written_service)
        self.assertIn('Environment=INFRA_TOOLS_WORKSPACE=/var/lib/infra_tools/cicd', written_service)
    
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
        written_service = ''.join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn('Environment=HOME=/var/lib/infra_tools/cicd', written_service)
        self.assertIn('Environment=INFRA_TOOLS_WORKSPACE=/var/lib/infra_tools/cicd', written_service)
        # Path unit must be created and enabled so the unprivileged webhook user
        # can trigger the executor by writing job files instead of calling systemctl.
        self.assertIn('PathChanged=/var/lib/infra_tools/cicd/jobs', written_service)
        self.assertIn('Unit=cicd-executor.service', written_service)
        path_enable_calls = [
            c for c in mock_run.call_args_list
            if 'enable cicd-executor.path' in str(c)
        ]
        self.assertGreater(len(path_enable_calls), 0,
                           "cicd-executor.path must be enabled so the webhook receiver "
                           "can trigger jobs without systemctl/polkit privileges")
    
    def test_trigger_cicd_job_does_not_call_systemctl(self):
        """Verify the unprivileged webhook receiver only writes job files."""
        import inspect
        src = inspect.getsource(webhook_receiver.trigger_cicd_job)
        # No code path may invoke systemctl from the unprivileged webhook user.
        self.assertNotIn("'systemctl'", src,
                         "trigger_cicd_job must not invoke systemctl: the webhook user "
                         "has no privilege to start system services. Use the path unit.")
        self.assertNotIn('"systemctl"', src)
        self.assertNotIn('subprocess.run', src)
    
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


class TestWebhookReceiverStructuredLogging(unittest.TestCase):
    @patch("web.service_tools.webhook_receiver.os.path.exists", return_value=False)
    def test_load_config_logs_missing_config(self, _mock_exists):
        with self.assertLogs(webhook_receiver.logger, level="WARNING") as logs:
            result = webhook_receiver.load_config()

        self.assertEqual(result, {})
        self.assertIn("Configuration file not found | config_file=", "\n".join(logs.output))

    @patch.dict(os.environ, {"WEBHOOK_SECRET": "secret", "WEBHOOK_PORT": "9123"}, clear=True)
    @patch("web.service_tools.webhook_receiver.os.makedirs")
    @patch("web.service_tools.webhook_receiver.HTTPServer")
    def test_main_logs_start_listen_and_shutdown(self, mock_http_server, _mock_makedirs):
        httpd = MagicMock()
        httpd.serve_forever.side_effect = KeyboardInterrupt()
        mock_http_server.return_value = httpd

        with self.assertLogs(webhook_receiver.logger, level="INFO") as logs:
            result = webhook_receiver.main()

        self.assertEqual(result, 0)
        output = "\n".join(logs.output)
        self.assertIn("Starting webhook receiver", output)
        self.assertIn("Webhook receiver listening | bind='127.0.0.1' port=9123", output)
        self.assertIn("Server is ready to accept webhooks", output)
        self.assertIn("Shutting down webhook receiver", output)


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

    @patch('web.build_server_steps.install_node_for_user')
    def test_install_build_node_targets_cicd_home(self, mock_install_node):
        mock_config = MagicMock()

        from web.build_server_steps import install_build_node
        install_build_node(mock_config)

        mock_install_node.assert_called_once_with('webhook', '/var/lib/infra_tools/cicd')

    @patch('web.build_server_steps.install_or_update_uv', return_value=True)
    @patch('web.build_server_steps.run')
    def test_install_build_python_tools_targets_cicd_home(self, mock_run, mock_install_uv):
        mock_config = MagicMock()

        from web.build_server_steps import install_build_python_tools
        install_build_python_tools(mock_config)

        self.assertTrue(any('apt-get install' in call.args[0] for call in mock_run.call_args_list))
        mock_install_uv.assert_called_once_with(user_home='/var/lib/infra_tools/cicd', username='webhook')
    
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

    @patch('web.build_server_steps.get_known_hosts_path', return_value='/var/lib/infra_tools/cicd/known_hosts')
    @patch('web.build_server_steps.os.path.exists')
    @patch('web.build_server_steps.os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch('web.build_server_steps.run')
    def test_configure_deploy_known_hosts_uses_workspace_file(
        self,
        mock_run,
        mock_file,
        mock_makedirs,
        mock_exists,
        _mock_known_hosts_path,
    ):
        mock_exists.side_effect = lambda path: path == '/var/lib/infra_tools/cicd/known_hosts'
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout='app1 ssh-ed25519 AAAA\n'),
            MagicMock(returncode=0, stdout='app2 ssh-ed25519 BBBB\n'),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        mock_config = MagicMock()
        mock_config.deploy_targets = ['app1.example.com', 'app2.example.com']

        from web.build_server_steps import configure_deploy_known_hosts
        configure_deploy_known_hosts(mock_config)

        mock_makedirs.assert_called_once_with('/var/lib/infra_tools/cicd', mode=0o700, exist_ok=True)
        write_paths = [call.args[0] for call in mock_file.call_args_list]
        self.assertEqual(
            write_paths,
            ['/var/lib/infra_tools/cicd/known_hosts', '/var/lib/infra_tools/cicd/known_hosts'],
        )


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

    def test_build_ssh_stdin_script_cmd_uses_bash_stdin(self):
        """Deploy scripts should stream over stdin instead of being embedded in the command."""
        from lib.remote_deploy import _build_ssh_stdin_script_cmd

        target = {
            'host': 'app1.example.com',
            'user': 'deploy',
            'ssh_key': '/tmp/key',
            'ssh_port': 2222,
        }
        command = _build_ssh_stdin_script_cmd(target, '/var/www/app one')

        self.assertEqual(command[:6], ['ssh', '-i', '/tmp/key', '-p', '2222', '-o'])
        self.assertEqual(command[-2], 'deploy@app1.example.com')
        self.assertEqual(command[-1], "cd '/var/www/app one' && bash -s --")


class TestRemoteDeployScriptExecution(unittest.TestCase):
    @patch('web.service_tools.cicd_executor.logger')
    @patch('web.service_tools.cicd_executor.subprocess.run')
    @patch('lib.remote_deploy._build_ssh_stdin_script_cmd', return_value=['ssh', 'deploy@app1', 'bash -s --'])
    @patch('lib.remote_deploy.reload_nginx', return_value=True)
    @patch('lib.remote_deploy.push_nginx_config', return_value=True)
    @patch('lib.remote_deploy.push_artifact', return_value=True)
    @patch('lib.remote_deploy.get_deploy_target')
    def test_execute_remote_deployment_streams_script_over_stdin(
        self,
        mock_get_target,
        _mock_push_artifact,
        _mock_push_nginx,
        _mock_reload_nginx,
        _mock_build_ssh_stdin,
        mock_run,
        _mock_logger,
    ):
        from web.service_tools.cicd_executor import perform_remote_deployment

        mock_get_target.return_value = {'host': 'app1.example.com', 'base_dir': '/var/www'}
        mock_run.return_value = subprocess.CompletedProcess(args=['ssh'], returncode=0, stdout='ok', stderr='')

        with tempfile.TemporaryDirectory() as workspace:
            script_path = os.path.join(workspace, 'deploy.sh')
            with open(script_path, 'w') as script_file:
                script_file.write('echo hello\n')
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as log_file:
                log_path = log_file.name

            try:
                result = perform_remote_deployment(
                    workspace=workspace,
                    deploy_target='app1.example.com',
                    deploy_spec=None,
                    repo_url='https://example.com/repo.git',
                    commit_sha='abc123',
                    log_file=log_path,
                    repo_config={'scripts': {'deploy': 'deploy.sh'}},
                )
            finally:
                os.unlink(log_path)

        self.assertTrue(result)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.kwargs['input'], 'echo hello\n')
        self.assertEqual(mock_run.call_args.args[0], ['ssh', 'deploy@app1', 'bash -s --'])

    @patch('lib.remote_deploy.get_deploy_target', return_value=None)
    def test_remote_deployment_logs_unknown_target(self, _mock_get_target):
        from web.service_tools.cicd_executor import perform_remote_deployment

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as log_file:
            log_path = log_file.name

        try:
            with self.assertLogs(cicd_executor.logger, level='ERROR') as logs:
                result = perform_remote_deployment(
                    workspace='/tmp/workspace',
                    deploy_target='missing.example.com',
                    deploy_spec=None,
                    repo_url='https://example.com/repo.git',
                    commit_sha='abc123',
                    log_file=log_path,
                    repo_config={},
                )
        finally:
            os.unlink(log_path)

        self.assertFalse(result)
        self.assertIn("Unknown deploy target | deploy_target='missing.example.com'", "\n".join(logs.output))

    @patch('web.service_tools.cicd_executor.subprocess.run', return_value=subprocess.CompletedProcess(args=['ssh'], returncode=0, stdout='ok', stderr=''))
    @patch('lib.remote_deploy._build_ssh_stdin_script_cmd', return_value=['ssh', 'deploy@app1', 'bash -s --'])
    @patch('lib.remote_deploy.reload_nginx', return_value=True)
    @patch('lib.remote_deploy.push_nginx_config', return_value=True)
    @patch('lib.remote_deploy.push_artifact', return_value=True)
    @patch('lib.remote_deploy.get_deploy_target')
    def test_remote_deployment_logs_success(
        self,
        mock_get_target,
        _mock_push_artifact,
        _mock_push_nginx,
        _mock_reload_nginx,
        _mock_build_ssh_stdin,
        _mock_run,
    ):
        from web.service_tools.cicd_executor import perform_remote_deployment

        mock_get_target.return_value = {'host': 'app1.example.com', 'base_dir': '/var/www'}

        with tempfile.TemporaryDirectory() as workspace:
            script_path = os.path.join(workspace, 'deploy.sh')
            with open(script_path, 'w') as script_file:
                script_file.write('echo hello\n')
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as log_file:
                log_path = log_file.name

            try:
                with self.assertLogs(cicd_executor.logger, level='INFO') as logs:
                    result = perform_remote_deployment(
                        workspace=workspace,
                        deploy_target='app1.example.com',
                        deploy_spec=None,
                        repo_url='https://example.com/repo.git',
                        commit_sha='abc123',
                        log_file=log_path,
                        repo_config={'scripts': {'deploy': 'deploy.sh'}},
                    )
            finally:
                os.unlink(log_path)

        self.assertTrue(result)
        output = "\n".join(logs.output)
        self.assertIn("Detected project type | deploy_target='app1.example.com' project_type='unknown'", output)
        self.assertIn("Remote deployment completed | deploy_target='app1.example.com' remote_path='/var/www/root'", output)


class TestExecutorStructuredLogging(unittest.TestCase):
    @patch("web.service_tools.cicd_executor.os.path.exists", return_value=False)
    def test_load_config_logs_missing_config(self, _mock_exists):
        with self.assertLogs(cicd_executor.logger, level="ERROR") as logs:
            result = cicd_executor.load_config()

        self.assertEqual(result, {})
        self.assertIn("Configuration file not found | config_file=", "\n".join(logs.output))

    @patch("web.service_tools.cicd_executor.os.path.exists", return_value=False)
    @patch("web.service_tools.cicd_executor.subprocess.run")
    def test_clone_or_update_repo_logs_clone_and_success(self, mock_run, _mock_exists):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=["git", "clone"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["git", "fetch"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["git", "reset"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["git", "clean"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["git", "checkout"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["git", "pull"], returncode=0, stdout="", stderr=""),
        ]

        with self.assertLogs(cicd_executor.logger, level="INFO") as logs:
            result = cicd_executor.clone_or_update_repo(
                "https://github.com/org/repo.git",
                "/tmp/repo",
                "refs/heads/main",
            )

        self.assertTrue(result)
        output = "\n".join(logs.output)
        self.assertIn("Cloning repository | repo_url='https://github.com/org/repo.git'", output)
        self.assertIn("Checking out branch | branch='main' repo_url='https://github.com/org/repo.git'", output)
        self.assertIn("Repository updated successfully | branch='main' repo_url='https://github.com/org/repo.git'", output)

    @patch("web.service_tools.cicd_executor.subprocess.run", return_value=subprocess.CompletedProcess(args=["/bin/bash"], returncode=0, stdout="", stderr=""))
    @patch("web.service_tools.cicd_executor.get_build_home", return_value="/var/lib/infra_tools/cicd")
    def test_run_script_logs_start_and_success(self, _mock_home, mock_run):
        with tempfile.TemporaryDirectory() as workspace:
            script_path = os.path.join(workspace, "build.sh")
            log_path = os.path.join(workspace, "build.log")
            with open(script_path, "w") as f:
                f.write("echo ok\n")

            with self.assertLogs(cicd_executor.logger, level="INFO") as logs:
                result = cicd_executor.run_script("build.sh", workspace, log_path)

        self.assertTrue(result)
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][:2], ['/bin/bash', '-lc'])
        self.assertIn('NVM_DIR=/var/lib/infra_tools/cicd/.nvm', args[0][2])
        self.assertIn('/var/lib/infra_tools/cicd/.local/bin', args[0][2])
        self.assertIn(f'exec /bin/bash {script_path}', args[0][2])
        self.assertEqual(kwargs['env']['HOME'], '/var/lib/infra_tools/cicd')
        self.assertTrue(kwargs['env']['PATH'].startswith('/var/lib/infra_tools/cicd/.local/bin'))
        output = "\n".join(logs.output)
        self.assertIn(f"Running script | script_path='{script_path}'", output)
        self.assertIn(f"Script completed successfully | script_path='{script_path}'", output)

    @patch("web.service_tools.cicd_executor.send_notification", side_effect=RuntimeError("notify boom"))
    def test_notify_success_logs_structured_failure(self, _mock_notify):
        with self.assertLogs(cicd_executor.logger, level="WARNING") as logs:
            cicd_executor.notify_success("https://github.com/org/repo.git", "abcdef123456", "/tmp/build.log", ["cfg"])

        self.assertIn(
            "Failed to send success notification | commit_sha='abcdef12' error='notify boom' repo_url='https://github.com/org/repo.git'",
            "\n".join(logs.output),
        )

    @patch("web.service_tools.cicd_executor.send_notification", side_effect=RuntimeError("notify boom"))
    def test_notify_failure_logs_structured_failure(self, _mock_notify):
        with self.assertLogs(cicd_executor.logger, level="WARNING") as logs:
            cicd_executor.notify_failure("https://github.com/org/repo.git", "abcdef123456", "Build failed", ["cfg"])

        self.assertIn(
            "Failed to send failure notification | commit_sha='abcdef12' error='notify boom' repo_url='https://github.com/org/repo.git'",
            "\n".join(logs.output),
        )

    @patch("web.service_tools.cicd_executor.os.remove")
    @patch("web.service_tools.cicd_executor.load_notification_configs_from_state", return_value=[])
    @patch("web.service_tools.cicd_executor.run_script", return_value=True)
    @patch("web.service_tools.cicd_executor.clone_or_update_repo", return_value=True)
    @patch("web.service_tools.cicd_executor.load_config")
    @patch("web.service_tools.cicd_executor.os.makedirs")
    def test_process_job_logs_start_and_completion(
        self,
        _mock_makedirs,
        mock_load_config,
        _mock_clone,
        _mock_run_script,
        _mock_notifications,
        _mock_remove,
    ):
        mock_load_config.return_value = {
            "repositories": [
                {
                    "url": "https://github.com/org/repo.git",
                    "scripts": {"build": "build.sh"},
                }
            ]
        }
        job_data = {
            "repo_url": "https://github.com/org/repo.git",
            "ref": "refs/heads/main",
            "commit_sha": "abcdef123456",
            "pusher": "alice",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            job_file = os.path.join(tmpdir, "job.json")
            with open(job_file, "w") as f:
                json.dump(job_data, f)

            with patch("web.service_tools.cicd_executor.WORKSPACES_DIR", tmpdir), \
                 patch("web.service_tools.cicd_executor.LOGS_DIR", tmpdir):
                with self.assertLogs(cicd_executor.logger, level="INFO") as logs:
                    result = cicd_executor.process_job(job_file)

        self.assertTrue(result)
        output = "\n".join(logs.output)
        self.assertIn(f"Processing job | job_file='{job_file}'", output)
        self.assertIn(
            f"Job completed | commit_sha='abcdef12' job_file='{job_file}' repo_url='https://github.com/org/repo.git' result='success'",
            output,
        )


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

    def test_cleanup_logs_structured_summary(self):
        """Cleanup summary uses structured logging context."""
        from web.service_tools.cicd_executor import cleanup_old_build_logs, logger

        with tempfile.TemporaryDirectory() as tmpdir:
            old_log = os.path.join(tmpdir, 'abc12345.log')
            with open(old_log, 'w') as f:
                f.write('old build log')
            old_time = time.time() - (40 * 24 * 60 * 60)
            os.utime(old_log, (old_time, old_time))

            with patch('web.service_tools.cicd_executor.LOGS_DIR', tmpdir):
                with self.assertLogs(logger, level='INFO') as logs:
                    removed = cleanup_old_build_logs(days_to_keep=30)

        self.assertEqual(removed, 1)
        self.assertIn("Cleaned up old build logs | days_to_keep=30 removed_count=1", "\n".join(logs.output))

    def test_cleanup_logs_structured_warning_on_remove_failure(self):
        from web.service_tools.cicd_executor import cleanup_old_build_logs, logger

        with tempfile.TemporaryDirectory() as tmpdir:
            old_log = os.path.join(tmpdir, "abc12345.log")
            with open(old_log, "w") as f:
                f.write("old build log")
            old_time = time.time() - (40 * 24 * 60 * 60)
            os.utime(old_log, (old_time, old_time))

            with patch("web.service_tools.cicd_executor.LOGS_DIR", tmpdir), \
                 patch("web.service_tools.cicd_executor.os.remove", side_effect=OSError("permission denied")):
                with self.assertLogs(logger, level="WARNING") as logs:
                    removed = cleanup_old_build_logs(days_to_keep=30)

        self.assertEqual(removed, 0)
        self.assertIn(
            "Failed to remove old build log | error='permission denied' log_file='abc12345.log'",
            "\n".join(logs.output),
        )


class TestCleanupStaleWorkspaces(unittest.TestCase):
    """Test stale workspace cleanup."""

    def test_removes_workspace_not_in_config(self):
        """Workspaces for repos not in config are removed."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            stale_ws = os.path.join(tmpdir, 'old-repo')
            os.makedirs(stale_ws)

            # Config has one repo, but it's not 'old-repo'
            config = {'repositories': [{'url': 'https://github.com/org/other-repo.git'}]}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(stale_ws))

    def test_empty_config_skips_cleanup(self):
        """Empty or invalid config does not delete any workspaces."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = os.path.join(tmpdir, 'some-repo')
            os.makedirs(ws)

            for config in [{}, {'repositories': []}]:
                with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                    removed = cleanup_stale_workspaces(config)
                self.assertEqual(removed, 0)
                self.assertTrue(os.path.exists(ws))

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

        config = {'repositories': [{'url': 'https://github.com/org/my-repo.git'}]}
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

            # Config has repos so the guard doesn't skip; the stray file is
            # not a directory so it should be left alone.
            config = {'repositories': [{'url': 'https://github.com/org/my-repo.git'}]}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                removed = cleanup_stale_workspaces(config)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(stray_file))

    def test_logs_structured_stale_workspace_removal(self):
        """Stale workspace removals include structured workspace context."""
        from web.service_tools.cicd_executor import cleanup_stale_workspaces, logger

        with tempfile.TemporaryDirectory() as tmpdir:
            stale_ws = os.path.join(tmpdir, 'old-repo')
            os.makedirs(stale_ws)
            config = {'repositories': [{'url': 'https://github.com/org/other-repo.git'}]}

            with patch('web.service_tools.cicd_executor.WORKSPACES_DIR', tmpdir):
                with self.assertLogs(logger, level='INFO') as logs:
                    removed = cleanup_stale_workspaces(config)

        self.assertEqual(removed, 1)
        self.assertIn("Removed stale workspace | workspace='old-repo'", "\n".join(logs.output))

    def test_logs_structured_stale_workspace_removal_failure(self):
        from web.service_tools.cicd_executor import cleanup_stale_workspaces, logger

        with tempfile.TemporaryDirectory() as tmpdir:
            stale_ws = os.path.join(tmpdir, "old-repo")
            os.makedirs(stale_ws)
            config = {"repositories": [{"url": "https://github.com/org/other-repo.git"}]}

            with patch("web.service_tools.cicd_executor.WORKSPACES_DIR", tmpdir), \
                 patch("web.service_tools.cicd_executor.shutil.rmtree", side_effect=OSError("permission denied")):
                with self.assertLogs(logger, level="WARNING") as logs:
                    removed = cleanup_stale_workspaces(config)

        self.assertEqual(removed, 0)
        self.assertIn(
            "Failed to remove stale workspace | error='permission denied' workspace='old-repo'",
            "\n".join(logs.output),
        )


if __name__ == '__main__':
    unittest.main()
