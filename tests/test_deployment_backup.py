"""Tests for database backup functionality in lib/deployment.py."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from typing import cast
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.deployment import DeploymentOrchestrator

# Capture the real os.path.exists before any @patch decorators replace it.
# This is needed by TestSkippedDeploymentServiceRecreation to avoid infinite
# recursion when selectively mocking os.path.exists.
_real_exists = os.path.exists


class TestDatabaseBackup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    def test_get_backup_dir(self):
        """Test backup directory path generation."""
        backup_dir = self.orchestrator._get_backup_dir("test_app")
        expected = os.path.join(self.tmpdir, ".infra_tools_shared", "test_app", "backups")
        self.assertEqual(backup_dir, expected)
    
    def test_backup_database_success(self):
        """Test successful database backup."""
        # Create a fake database file
        db_path = os.path.join(self.tmpdir, "test.sqlite3")
        with open(db_path, 'w') as f:
            f.write("fake database content")
        
        backup_dir = os.path.join(self.tmpdir, "backups")
        backup_path = self.orchestrator._backup_database(db_path, backup_dir, "test_app")
        
        self.assertIsNotNone(backup_path)
        backup_path = cast(str, backup_path)
        self.assertTrue(os.path.exists(backup_path))
        self.assertIn("test_app_production_", backup_path)
        self.assertTrue(backup_path.endswith(".sqlite3"))
        
        # Verify content was copied
        with open(backup_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "fake database content")
        self.assertEqual(os.stat(backup_dir).st_mode & 0o777, 0o750)
        self.assertEqual(os.stat(backup_path).st_mode & 0o777, 0o640)
    
    def test_backup_database_nonexistent(self):
        """Test backup of non-existent database returns None."""
        db_path = os.path.join(self.tmpdir, "nonexistent.sqlite3")
        backup_dir = os.path.join(self.tmpdir, "backups")
        
        backup_path = self.orchestrator._backup_database(db_path, backup_dir, "test_app")
        
        self.assertIsNone(backup_path)
    
    def test_backup_database_empty_file(self):
        """Test backup of empty database file fails verification."""
        # Create empty database file
        db_path = os.path.join(self.tmpdir, "empty.sqlite3")
        open(db_path, 'a').close()
        
        backup_dir = os.path.join(self.tmpdir, "backups")
        backup_path = self.orchestrator._backup_database(db_path, backup_dir, "test_app")
        
        # Empty files should fail verification
        self.assertIsNone(backup_path)
    
    def test_backup_database_follows_symlink(self):
        """Test backup follows symlinks to actual database file."""
        # Create actual database file
        actual_db = os.path.join(self.tmpdir, "actual.sqlite3")
        with open(actual_db, 'w') as f:
            f.write("actual database")
        
        # Create symlink to it
        link_path = os.path.join(self.tmpdir, "link.sqlite3")
        os.symlink(actual_db, link_path)
        
        backup_dir = os.path.join(self.tmpdir, "backups")
        backup_path = self.orchestrator._backup_database(link_path, backup_dir, "test_app")
        
        self.assertIsNotNone(backup_path)
        backup_path = cast(str, backup_path)
        with open(backup_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "actual database")
    
    def test_cleanup_old_backups(self):
        """Test old backups are removed, keeping only recent ones."""
        backup_dir = os.path.join(self.tmpdir, "backups")
        os.makedirs(backup_dir)
        
        # Create 15 fake backup files with different timestamps
        for i in range(15):
            backup_file = os.path.join(backup_dir, f"test_app_production_{i:04d}.sqlite3")
            with open(backup_file, 'w') as f:
                f.write(f"backup {i}")
            # Set different modification times
            timestamp = time.time() - (15 - i) * 3600  # Each hour apart
            os.utime(backup_file, (timestamp, timestamp))
        
        # Should keep 10 most recent
        self.orchestrator._cleanup_old_backups(backup_dir, "test_app", keep=10)
        
        remaining = [f for f in os.listdir(backup_dir) if f.endswith(".sqlite3")]
        self.assertEqual(len(remaining), 10)
        
        # Verify oldest ones were removed (0-4) and newest kept (5-14)
        for i in range(5):
            self.assertNotIn(f"test_app_production_{i:04d}.sqlite3", remaining)
        for i in range(5, 15):
            self.assertIn(f"test_app_production_{i:04d}.sqlite3", remaining)
    
    def test_cleanup_only_affects_target_app(self):
        """Test cleanup only removes backups for the specified app."""
        backup_dir = os.path.join(self.tmpdir, "backups")
        os.makedirs(backup_dir)
        
        # Create backups for multiple apps
        for app in ["app1", "app2"]:
            for i in range(15):
                backup_file = os.path.join(backup_dir, f"{app}_production_{i:04d}.sqlite3")
                with open(backup_file, 'w') as f:
                    f.write(f"{app} backup {i}")
        
        # Clean up only app1, keeping 5
        self.orchestrator._cleanup_old_backups(backup_dir, "app1", keep=5)
        
        app1_remaining = [f for f in os.listdir(backup_dir) if f.startswith("app1_")]
        app2_remaining = [f for f in os.listdir(backup_dir) if f.startswith("app2_")]
        
        self.assertEqual(len(app1_remaining), 5)
        self.assertEqual(len(app2_remaining), 15)  # app2 untouched


class TestMigrationDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    @patch('lib.deployment.run')
    def test_check_pending_migrations_true(self, mock_run):
        """Test detection of pending migrations."""
        mock_result = MagicMock()
        mock_result.returncode = 0  # grep found ' down ' status
        mock_run.return_value = mock_result
        
        has_pending = self.orchestrator._check_pending_migrations(
            self.tmpdir, 
            "RAILS_ENV=production"
        )
        
        self.assertTrue(has_pending)
    
    @patch('lib.deployment.run')
    def test_check_pending_migrations_false(self, mock_run):
        """Test detection when no pending migrations."""
        mock_result = MagicMock()
        mock_result.returncode = 1  # grep didn't find ' down '
        mock_run.return_value = mock_result
        
        has_pending = self.orchestrator._check_pending_migrations(
            self.tmpdir,
            "RAILS_ENV=production"
        )
        
        self.assertFalse(has_pending)
    
    @patch('lib.deployment.run')
    def test_check_pending_migrations_error_assumes_true(self, mock_run):
        """Test that errors default to assuming migrations needed."""
        mock_run.side_effect = Exception("Command failed")
        
        has_pending = self.orchestrator._check_pending_migrations(
            self.tmpdir,
            "RAILS_ENV=production"
        )
        
        # Should assume migrations are needed when unsure
        self.assertTrue(has_pending)


class TestRailsBuildWithBackup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    @patch('lib.deployment.run')
    def test_backup_created_before_migration(self, mock_run):
        """Test that backup is created before running migrations."""
        # Setup: create project structure with existing database
        project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(project_path, "db"))
        
        db_path = os.path.join(project_path, "db", "production.sqlite3")
        with open(db_path, 'w') as f:
            f.write("existing database data")
        
        # Mock run to succeed and indicate pending migrations
        def mock_run_impl(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            if 'migrate:status' in cmd and 'grep' in cmd:
                result.returncode = 0  # Has pending migrations
            return result
        
        mock_run.side_effect = mock_run_impl
        
        # Run build with backup
        self.orchestrator._build_rails_project(project_path, app_name="test_app")
        
        # Verify backup was created
        backup_dir = self.orchestrator._get_backup_dir("test_app")
        backups = [f for f in os.listdir(backup_dir) if f.endswith(".sqlite3")]
        self.assertEqual(len(backups), 1)
        self.assertIn("test_app_production_", backups[0])
    
    @patch('lib.deployment.run')
    def test_no_backup_without_app_name(self, mock_run):
        """Test that backup is skipped if app_name is not provided."""
        project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(project_path, "db"))
        
        db_path = os.path.join(project_path, "db", "production.sqlite3")
        with open(db_path, 'w') as f:
            f.write("existing database")
        
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        
        # Run without app_name
        self.orchestrator._build_rails_project(project_path, app_name=None)
        
        # No backup should be created
        shared_dir = os.path.join(self.tmpdir, ".infra_tools_shared")
        self.assertFalse(os.path.exists(shared_dir))
    
    @patch('lib.deployment.run')
    def test_seeds_skipped_for_existing_database(self, mock_run):
        """Test that seeds are skipped when database already exists."""
        project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(project_path, "db"))
        
        # Create existing database
        db_path = os.path.join(project_path, "db", "production.sqlite3")
        with open(db_path, 'w') as f:
            f.write("existing database")
        
        # Create seeds file
        seeds_path = os.path.join(project_path, "db", "seeds.rb")
        with open(seeds_path, 'w') as f:
            f.write("User.create!(email: 'admin@test.com')")
        
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        
        self.orchestrator._build_rails_project(project_path, app_name="test_app")
        
        # Verify db:seed was NOT called
        seed_calls = [call for call in mock_run.call_args_list 
                     if 'db:seed' in str(call)]
        self.assertEqual(len(seed_calls), 0)
    
    @patch('lib.deployment.run')
    def test_seeds_run_for_new_database(self, mock_run):
        """Test that seeds run when database doesn't exist."""
        project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(project_path, "db"))
        
        # NO existing database - just seeds file
        seeds_path = os.path.join(project_path, "db", "seeds.rb")
        with open(seeds_path, 'w') as f:
            f.write("User.create!(email: 'admin@test.com')")
        
        mock_run.return_value = MagicMock(returncode=0, stdout="Seeds loaded")
        
        self.orchestrator._build_rails_project(project_path, app_name="test_app")
        
        # Verify db:seed WAS called
        seed_calls = [call for call in mock_run.call_args_list 
                     if 'db:seed' in str(call)]
        self.assertGreater(len(seed_calls), 0)


class TestSeedFileDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        self.project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(self.project_path, "db"))
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    def test_get_production_specific_seeds(self):
        """Test finding production-specific seeds file."""
        # Create production_seeds.rb in db/seeds/
        seeds_dir = os.path.join(self.project_path, "db", "seeds")
        os.makedirs(seeds_dir)
        prod_seeds = os.path.join(seeds_dir, "production_seeds.rb")
        with open(prod_seeds, 'w') as f:
            f.write("User.find_or_create_by!(username: 'admin')")
        
        result = self.orchestrator._get_seed_file_path(self.project_path, 'production')
        self.assertEqual(result, prod_seeds)
    
    def test_fallback_to_standard_seeds(self):
        """Test fallback to db/seeds.rb when no env-specific file exists."""
        seeds_file = os.path.join(self.project_path, "db", "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("User.create!(username: 'admin')")
        
        result = self.orchestrator._get_seed_file_path(self.project_path, 'production')
        self.assertEqual(result, seeds_file)
    
    def test_no_seeds_file(self):
        """Test returns None when no seeds file exists."""
        result = self.orchestrator._get_seed_file_path(self.project_path, 'production')
        self.assertIsNone(result)
    
    def test_priority_order(self):
        """Test that db/seeds/production_seeds.rb has priority over db/seeds.rb."""
        # Create both files
        seeds_dir = os.path.join(self.project_path, "db", "seeds")
        os.makedirs(seeds_dir)
        prod_seeds = os.path.join(seeds_dir, "production_seeds.rb")
        with open(prod_seeds, 'w') as f:
            f.write("# production seeds")
        
        standard_seeds = os.path.join(self.project_path, "db", "seeds.rb")
        with open(standard_seeds, 'w') as f:
            f.write("# standard seeds")
        
        result = self.orchestrator._get_seed_file_path(self.project_path, 'production')
        self.assertEqual(result, prod_seeds)


class TestSeedIdempotencyDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    def test_idempotent_find_or_create_by(self):
        """Test detection of idempotent find_or_create_by pattern."""
        seeds_file = os.path.join(self.tmpdir, "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("""
User.find_or_create_by!(username: 'admin') do |user|
  user.email = 'admin@example.com'
  user.password = 'password'
end
""")
        
        is_idempotent, reason = self.orchestrator._is_seeds_file_idempotent(seeds_file)
        self.assertTrue(is_idempotent)
        self.assertIn("idempotent", reason.lower())
    
    def test_dangerous_create_pattern(self):
        """Test detection of dangerous create! pattern."""
        seeds_file = os.path.join(self.tmpdir, "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("User.create!(username: 'admin', email: 'admin@example.com')")
        
        is_idempotent, reason = self.orchestrator._is_seeds_file_idempotent(seeds_file)
        self.assertFalse(is_idempotent)
        self.assertIn("create!", reason)
    
    def test_dangerous_delete_all(self):
        """Test detection of dangerous delete_all pattern."""
        seeds_file = os.path.join(self.tmpdir, "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("""
User.delete_all
User.create!(username: 'admin')
""")
        
        is_idempotent, reason = self.orchestrator._is_seeds_file_idempotent(seeds_file)
        self.assertFalse(is_idempotent)
        self.assertIn("delete_all", reason)
    
    def test_mixed_patterns(self):
        """Test detection when file has both safe and unsafe patterns."""
        seeds_file = os.path.join(self.tmpdir, "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("""
User.find_or_create_by!(username: 'admin')
Category.create!(name: 'Test')  # This is unsafe
""")
        
        is_idempotent, reason = self.orchestrator._is_seeds_file_idempotent(seeds_file)
        # Should detect as mixed/unsafe
        self.assertIn("create!", reason.lower())
    
    def test_first_or_create_pattern(self):
        """Test detection of first_or_create pattern."""
        seeds_file = os.path.join(self.tmpdir, "seeds.rb")
        with open(seeds_file, 'w') as f:
            f.write("User.where(username: 'admin').first_or_create(email: 'admin@example.com')")
        
        is_idempotent, reason = self.orchestrator._is_seeds_file_idempotent(seeds_file)
        self.assertTrue(is_idempotent)


class TestIntelligentSeeding(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        self.project_path = os.path.join(self.tmpdir, "project")
        os.makedirs(os.path.join(self.project_path, "db"))
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    @patch('lib.deployment.run')
    def test_idempotent_seeds_run_on_existing_db(self, mock_run):
        """Test that idempotent seeds run even on existing databases."""
        # Create existing database
        db_path = os.path.join(self.project_path, "db", "production.sqlite3")
        with open(db_path, 'w') as f:
            f.write("existing database")
        
        # Create idempotent seeds
        seeds_path = os.path.join(self.project_path, "db", "seeds.rb")
        with open(seeds_path, 'w') as f:
            f.write("User.find_or_create_by!(username: 'admin')")
        
        mock_run.return_value = MagicMock(returncode=0, stdout="Admin user created")
        
        self.orchestrator._build_rails_project(self.project_path, app_name="test_app")
        
        # Verify seeds WERE called
        seed_calls = [call for call in mock_run.call_args_list 
                     if 'db:seed' in str(call)]
        self.assertGreater(len(seed_calls), 0, "Seeds should run for idempotent files")
    
    @patch('lib.deployment.run')
    def test_non_idempotent_seeds_skipped_on_existing_db(self, mock_run):
        """Test that non-idempotent seeds are skipped on existing databases."""
        # Create existing database
        db_path = os.path.join(self.project_path, "db", "production.sqlite3")
        with open(db_path, 'w') as f:
            f.write("existing database")
        
        # Create non-idempotent seeds
        seeds_path = os.path.join(self.project_path, "db", "seeds.rb")
        with open(seeds_path, 'w') as f:
            f.write("User.create!(username: 'admin')")  # Not idempotent
        
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        
        self.orchestrator._build_rails_project(self.project_path, app_name="test_app")
        
        # Verify seeds were NOT called
        seed_calls = [call for call in mock_run.call_args_list 
                     if 'db:seed' in str(call)]
        self.assertEqual(len(seed_calls), 0, "Non-idempotent seeds should be skipped")
    
    @patch('lib.deployment.run')
    def test_production_specific_seeds_used(self, mock_run):
        """Test that production_seeds.rb is used when available."""
        # Create production-specific seeds
        seeds_dir = os.path.join(self.project_path, "db", "seeds")
        os.makedirs(seeds_dir)
        prod_seeds = os.path.join(seeds_dir, "production_seeds.rb")
        with open(prod_seeds, 'w') as f:
            f.write("User.find_or_create_by!(username: 'prod_admin')")
        
        # Also create standard seeds (should not be used)
        standard_seeds = os.path.join(self.project_path, "db", "seeds.rb")
        with open(standard_seeds, 'w') as f:
            f.write("User.create!(username: 'dev_admin')")
        
        mock_run.return_value = MagicMock(returncode=0, stdout="Production admin created")
        
        self.orchestrator._build_rails_project(self.project_path, app_name="test_app")
        
        # Verify production seeds were used (via rails runner)
        runner_calls = [call for call in mock_run.call_args_list 
                       if 'rails runner' in str(call) and 'production_seeds.rb' in str(call)]
        self.assertGreater(len(runner_calls), 0, "Production-specific seeds should be used")


class TestSkippedDeploymentServiceRecreation(unittest.TestCase):
    """Tests for ensuring Rails services are recreated when deployments are skipped."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        self.port_patcher = patch.object(
            self.orchestrator, '_find_free_port', return_value=3000
        )
        self.port_patcher.start()
        self.addCleanup(self.port_patcher.stop)
        
        # Create a fake Rails project directory
        self.app_dir = os.path.join(self.tmpdir, "example_com")
        os.makedirs(self.app_dir)
        
        # Make it detectable as Rails
        with open(os.path.join(self.app_dir, '.ruby-version'), 'w') as f:
            f.write('3.3.0')
        os.makedirs(os.path.join(self.app_dir, 'bin'), exist_ok=True)
        with open(os.path.join(self.app_dir, 'bin', 'rails'), 'w') as f:
            f.write('#!/usr/bin/env ruby')
        os.makedirs(os.path.join(self.app_dir, 'public'), exist_ok=True)
        
        # Save deployment metadata so it can be skipped
        from lib.deploy_utils import save_deployment_metadata
        save_deployment_metadata(self.app_dir, 'https://git.example.com/repo.git', 'abc123')
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
    
    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    @patch('os.path.exists')
    def test_skipped_deploy_recreates_missing_service(self, mock_exists, mock_run, mock_create_service):
        """When a deployment is skipped but the service file is missing, recreate it."""
        def selective_exists(path):
            # Service file does NOT exist (simulates cleanup_all_infra_services)
            if path.startswith('/etc/systemd/system/') and path.endswith('.service'):
                return False
            return _real_exists(path)
        
        mock_exists.side_effect = selective_exists
        mock_run.return_value = MagicMock(returncode=0)
        
        result = self.orchestrator.deploy_from_archive(
            source_path='/tmp/fake_source',
            domain='example.com',
            path='/',
            git_url='https://git.example.com/repo.git',
            commit_hash='abc123',
            full_deploy=False,
        )
        
        # Should have been skipped
        self.assertTrue(result.get('skipped'))
        
        # Service should have been recreated since the file was missing
        mock_create_service.assert_called_once()
        call_args = mock_create_service.call_args
        self.assertEqual(call_args[0][0], 'example_com')  # app_name
        self.assertIsNotNone(call_args[0][2])  # port
        self.assertEqual(call_args[0][3], 'rails-example_com')
        self.assertEqual(call_args[0][4], 'rails-example_com')
    
    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    @patch('os.path.exists')
    def test_skipped_deploy_does_not_recreate_existing_service(self, mock_exists, mock_run, mock_create_service):
        """When a deployment is skipped and the service file exists, don't recreate it."""
        def selective_exists(path):
            # Service file DOES exist
            if path == '/etc/systemd/system/rails-example_com.service':
                return True
            return _real_exists(path)
        
        mock_exists.side_effect = selective_exists
        mock_run.return_value = MagicMock(returncode=0)
        
        result = self.orchestrator.deploy_from_archive(
            source_path='/tmp/fake_source',
            domain='example.com',
            path='/',
            git_url='https://git.example.com/repo.git',
            commit_hash='abc123',
            full_deploy=False,
        )
        
        self.assertTrue(result.get('skipped'))

        # Service should NOT have been recreated
        mock_create_service.assert_not_called()

    @patch.object(DeploymentOrchestrator, '_prepare_rails_runtime_state')
    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    @patch('os.path.exists')
    def test_skipped_deploy_reconciles_runtime_state_for_existing_service(
        self, mock_exists, mock_run, mock_create_service, mock_prepare_runtime_state
    ):
        """A skipped deployment migrates persistent state even when the service already exists."""
        def selective_exists(path):
            if path == '/etc/systemd/system/rails-example_com.service':
                return True
            return _real_exists(path)

        mock_exists.side_effect = selective_exists
        mock_run.return_value = MagicMock(returncode=0)

        result = self.orchestrator.deploy_from_archive(
            source_path='/tmp/fake_source',
            domain='example.com',
            path='/',
            git_url='https://git.example.com/repo.git',
            commit_hash='abc123',
            full_deploy=False,
        )

        self.assertTrue(result.get('skipped'))
        mock_create_service.assert_not_called()
        mock_prepare_runtime_state.assert_called_once_with(
            os.path.join(self.tmpdir, ".infra_tools_shared", "example_com"),
            'rails-example_com',
        )

    @patch.object(DeploymentOrchestrator, '_service_file_user', return_value='rails')
    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    @patch('os.path.exists')
    def test_skipped_deploy_recreates_legacy_rails_user_service(
        self, mock_exists, mock_run, mock_create_service, _service_file_user
    ):
        """A skipped deployment migrates an existing service off the legacy rails user."""
        def selective_exists(path):
            if path == '/etc/systemd/system/rails-example_com.service':
                return True
            return _real_exists(path)

        mock_exists.side_effect = selective_exists
        mock_run.return_value = MagicMock(returncode=0)

        result = self.orchestrator.deploy_from_archive(
            source_path='/tmp/fake_source',
            domain='example.com',
            path='/',
            git_url='https://git.example.com/repo.git',
            commit_hash='abc123',
            full_deploy=False,
        )

        self.assertTrue(result.get('skipped'))
        mock_create_service.assert_called_once()
        call_args = mock_create_service.call_args
        self.assertEqual(call_args[0][3], 'rails-example_com')
        self.assertEqual(call_args[0][4], 'rails-example_com')


class TestRailsRuntimeStatePermissions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        self.persistent_root = os.path.join(self.tmpdir, ".infra_tools_shared", "example_com")
        for rel_dir in (
            "db",
            "backups",
            "storage",
            "log",
            "tmp",
            os.path.join("public", "uploads"),
            os.path.join("public", "system"),
        ):
            os.makedirs(os.path.join(self.persistent_root, rel_dir), exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    @patch('lib.deployment.run')
    def test_runtime_state_permissions_keep_private_state_non_world_readable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

        self.orchestrator._prepare_rails_runtime_state(self.persistent_root, 'rails-example_com')

        commands = [call.args[0] for call in mock_run.call_args_list]
        all_commands = "\n".join(commands)

        self.assertIn(f"chmod 755 {os.path.dirname(self.persistent_root)}", commands)
        self.assertIn(f"find {self.persistent_root} -type d -exec chmod 750", all_commands)
        self.assertIn(f"find {self.persistent_root} -type f -exec chmod 640", all_commands)
        self.assertIn(f"chmod 755 {self.persistent_root}", commands)
        self.assertIn("public/uploads", all_commands)
        self.assertIn("public/system", all_commands)
        self.assertIn("-type d -exec chmod 755", all_commands)
        self.assertIn("-type f -exec chmod 644", all_commands)
        self.assertNotIn("chmod 775", all_commands)
        self.assertNotIn("chmod 664", all_commands)


class TestRailsFrontendServePathDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orchestrator = DeploymentOrchestrator(base_dir=self.tmpdir)
        self.port_patcher = patch.object(
            self.orchestrator, '_find_free_port', return_value=3000
        )
        self.port_patcher.start()
        self.addCleanup(self.port_patcher.stop)

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_requires_index_html_for_frontend_serve_path(self):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        public_dir = os.path.join(frontend_path, "public")
        os.makedirs(public_dir)

        result = self.orchestrator._get_frontend_serve_path(frontend_path)

        self.assertIsNone(result)

    def test_accepts_built_frontend_with_index_html(self):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        dist_dir = os.path.join(frontend_path, "dist")
        os.makedirs(dist_dir)
        with open(os.path.join(dist_dir, "index.html"), 'w') as f:
            f.write("<html></html>")

        result = self.orchestrator._get_frontend_serve_path(frontend_path)

        self.assertEqual(result, dist_dir)

    @patch('lib.deployment.run')
    def test_build_node_project_requires_output_when_requested(self, mock_run):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        os.makedirs(frontend_path)
        with open(os.path.join(frontend_path, 'package.json'), 'w') as f:
            f.write('{"scripts": {"build": "vite build"}}')

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with self.assertRaisesRegex(RuntimeError, "no serveable index.html"):
            self.orchestrator._build_node_project(frontend_path, require_build_output=True)

    @patch('lib.deployment.run')
    def test_build_node_project_raises_on_build_failure_when_required(self, mock_run):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        os.makedirs(frontend_path)
        with open(os.path.join(frontend_path, 'package.json'), 'w') as f:
            f.write('{"scripts": {"build": "vite build"}}')

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="vite build failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "Frontend build failed"):
            self.orchestrator._build_node_project(frontend_path, require_build_output=True)

    @patch('lib.deployment.run')
    def test_build_node_project_uses_npm_ci_when_lockfile_exists(self, mock_run):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        os.makedirs(frontend_path)
        with open(os.path.join(frontend_path, 'package.json'), 'w') as f:
            f.write('{}')
        with open(os.path.join(frontend_path, 'package-lock.json'), 'w') as f:
            f.write('{}')

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        self.orchestrator._build_node_project(frontend_path)

        self.assertIn("npm ci", mock_run.call_args_list[0].args[0])
        self.assertNotIn("npm install", mock_run.call_args_list[0].args[0])
        self.assertIn("--before=", mock_run.call_args_list[0].args[0])

    @patch('lib.deployment.run')
    def test_build_node_project_uses_before_policy_for_npm_install_without_lockfile(self, mock_run):
        frontend_path = os.path.join(self.tmpdir, "frontend")
        os.makedirs(frontend_path)
        with open(os.path.join(frontend_path, 'package.json'), 'w') as f:
            f.write('{}')

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        self.orchestrator._build_node_project(frontend_path)

        self.assertIn("npm install", mock_run.call_args_list[0].args[0])
        self.assertIn("--before=", mock_run.call_args_list[0].args[0])

    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    @patch('os.path.exists')
    def test_skipped_deploy_raises_for_unbuilt_frontend(self, mock_exists, mock_run, mock_create_service):
        app_dir = os.path.join(self.tmpdir, "example_com")
        os.makedirs(app_dir)
        with open(os.path.join(app_dir, '.ruby-version'), 'w') as f:
            f.write('3.3.0')
        os.makedirs(os.path.join(app_dir, 'bin'), exist_ok=True)
        with open(os.path.join(app_dir, 'bin', 'rails'), 'w') as f:
            f.write('#!/usr/bin/env ruby')
        os.makedirs(os.path.join(app_dir, 'public'), exist_ok=True)
        os.mkdir(os.path.join(app_dir, 'frontend'))
        os.mkdir(os.path.join(app_dir, 'frontend', 'public'))
        with open(os.path.join(app_dir, 'frontend', 'package.json'), 'w') as f:
            f.write('{}')

        from lib.deploy_utils import save_deployment_metadata
        save_deployment_metadata(app_dir, 'https://git.example.com/repo.git', 'abc123')

        def selective_exists(path):
            if path == '/etc/systemd/system/rails-example_com.service':
                return True
            return _real_exists(path)

        mock_exists.side_effect = selective_exists
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

        with self.assertRaisesRegex(RuntimeError, 'Frontend build required'):
            self.orchestrator.deploy_from_archive(
                source_path='/tmp/fake_source',
                domain='example.com',
                path='/',
                git_url='https://git.example.com/repo.git',
                commit_hash='abc123',
                full_deploy=False,
            )

        mock_create_service.assert_not_called()

    @patch.object(DeploymentOrchestrator, '_link_rails_persistent_state_into_release')
    @patch.object(DeploymentOrchestrator, '_get_assigned_port', return_value=3000)
    @patch.object(DeploymentOrchestrator, '_get_frontend_serve_path', return_value=None)
    @patch.object(DeploymentOrchestrator, '_build_node_project')
    @patch.object(DeploymentOrchestrator, 'build_project')
    @patch('lib.deployment.create_rails_service')
    @patch('lib.deployment.run')
    def test_full_deploy_raises_if_frontend_serve_path_missing_after_validation(
        self,
        mock_run,
        mock_create_service,
        mock_build_project,
        mock_build_node_project,
        mock_get_frontend_serve_path,
        mock_get_assigned_port,
        mock_link_state,
    ):
        source_dir = os.path.join(self.tmpdir, "source")
        os.makedirs(os.path.join(source_dir, 'bin'), exist_ok=True)
        with open(os.path.join(source_dir, '.ruby-version'), 'w') as f:
            f.write('3.3.0')
        with open(os.path.join(source_dir, 'bin', 'rails'), 'w') as f:
            f.write('#!/usr/bin/env ruby')
        os.makedirs(os.path.join(source_dir, 'public'), exist_ok=True)
        os.makedirs(os.path.join(source_dir, 'frontend'), exist_ok=True)

        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

        with self.assertRaisesRegex(RuntimeError, 'Frontend build output could not be located after validation'):
            self.orchestrator.deploy_from_archive(
                source_path=source_dir,
                domain='example.com',
                path='/',
                git_url='https://git.example.com/repo.git',
                commit_hash='abc123',
                keep_source=True,
            )

        mock_build_project.assert_called_once()
        mock_build_node_project.assert_called_once()
        mock_get_frontend_serve_path.assert_called_once()
        mock_get_assigned_port.assert_called_once()
        mock_link_state.assert_called_once()
        mock_create_service.assert_called_once()
        call_args = mock_create_service.call_args
        self.assertEqual(call_args[0][3], 'rails-example_com')
        self.assertEqual(call_args[0][4], 'rails-example_com')


if __name__ == '__main__':
    unittest.main()
