"""Tests for database backup functionality in lib/deployment.py."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.deployment import DeploymentOrchestrator


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
        self.assertTrue(os.path.exists(backup_path))
        self.assertIn("test_app_production_", backup_path)
        self.assertTrue(backup_path.endswith(".sqlite3"))
        
        # Verify content was copied
        with open(backup_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "fake database content")
    
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


if __name__ == '__main__':
    unittest.main()
