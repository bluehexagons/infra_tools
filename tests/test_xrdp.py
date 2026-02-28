"""Tests for XRDP configuration functions."""

from __future__ import annotations
import unittest
from unittest.mock import Mock, patch

from lib.config import SetupConfig
from desktop.xrdp_steps import _generate_sesman_ini, install_xrdp, harden_xrdp
from desktop.desktop_environment_steps import configure_xfce_for_rdp


class TestGenerateSesmanIni(unittest.TestCase):
    """Test sesman.ini generation."""
    
    def test_generates_valid_ini_format(self):
        """sesman.ini should have proper INI sections."""
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        cleanup_path = "/opt/cleanup.py"
        
        result = _generate_sesman_ini(config, cleanup_path)
        
        # Check required sections exist
        self.assertIn("[Globals]", result)
        self.assertIn("[Security]", result)
        self.assertIn("[Sessions]", result)
        self.assertIn("[Logging]", result)
        self.assertIn("[Xorg]", result)
        
    def test_uses_xorg_backend_only(self):
        """Should use Xorg backend, not Xvnc."""
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        cleanup_path = "/opt/cleanup.py"
        
        result = _generate_sesman_ini(config, cleanup_path)
        
        # Xorg section should exist
        self.assertIn("[Xorg]", result)
        self.assertIn("param=/usr/lib/xorg/Xorg", result)
        self.assertIn("param=/etc/X11/xrdp/xorg.conf", result)
        
        # Xvnc section should NOT exist
        self.assertNotIn("[Xvnc]", result)
        self.assertNotIn("Xvnc", result)
        
    def test_includes_cleanup_script_path(self):
        """EndSessionCommand should reference cleanup script."""
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        cleanup_path = "/custom/path/cleanup.py"
        
        result = _generate_sesman_ini(config, cleanup_path)
        
        self.assertIn(f"EndSessionCommand={cleanup_path}", result)
        
    def test_security_settings(self):
        """Should include security restrictions."""
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        cleanup_path = "/opt/cleanup.py"
        
        result = _generate_sesman_ini(config, cleanup_path)
        
        # Security settings
        self.assertIn("AllowRootLogin=false", result)
        self.assertIn("TerminalServerUsers=remoteusers", result)
        self.assertIn("AlwaysGroupCheck=true", result)


class TestInstallXrdp(unittest.TestCase):
    """Test XRDP installation and configuration."""
    
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.has_gpu_access')
    def test_installs_required_packages(self, mock_gpu, mock_open, mock_makedirs, mock_exists, mock_run):
        """Should install xrdp, xorgxrdp, and utilities."""
        mock_exists.return_value = True
        mock_gpu.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        # Check apt-get install was called with correct packages
        install_calls = [c for c in mock_run.call_args_list if 'apt-get install' in str(c)]
        self.assertGreater(len(install_calls), 0)
        
        # First install call should have xrdp packages
        first_install = str(install_calls[0])
        self.assertIn("xrdp", first_install)
        self.assertIn("xorgxrdp", first_install)
        self.assertIn("dbus-x11", first_install)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.has_gpu_access')
    def test_creates_xwrapper_config(self, mock_gpu, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should create /etc/X11/Xwrapper.config with correct content."""
        mock_exists.return_value = True
        mock_gpu.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        # Check that Xwrapper.config was written
        write_calls = [c for c in mock_open_func().write.call_args_list]
        xwrapper_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        self.assertIn("allowed_users=anybody", xwrapper_content)
        self.assertIn("needs_root_rights=no", xwrapper_content)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.has_gpu_access')
    def test_writes_sesman_ini(self, mock_gpu, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should write sesman.ini with Xorg backend."""
        mock_exists.return_value = True
        mock_gpu.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        # Check that sesman.ini content was written
        write_calls = [c for c in mock_open_func().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        self.assertIn("[Xorg]", combined_content)
        self.assertIn("param=/usr/lib/xorg/Xorg", combined_content)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.has_gpu_access')
    def test_creates_xorg_conf_with_correct_settings(self, mock_gpu, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """X.Org config should have correct driver and screen size."""
        # Mock that xorg.conf doesn't exist yet
        def exists_side_effect(path):
            if path == "/etc/X11/xrdp/xorg.conf":
                return False
            return True
        mock_exists.side_effect = exists_side_effect
        
        mock_gpu.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        # Find the xorg.conf content
        write_calls = [c for c in mock_open_func().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        # Check for xrdpdev driver
        self.assertIn('Driver "xrdpdev"', combined_content)
        
        # Check for disabled glamor (to prevent crashes)
        self.assertIn('UseGlamor', combined_content)
        self.assertIn('false', combined_content)
        
        # Check for virtual screen size (updated for 4K support)
        self.assertIn('Virtual 3840 2160', combined_content)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.has_gpu_access')
    def test_adds_user_to_video_groups_when_gpu_available(self, mock_gpu, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should add user to video/render groups when GPU is available."""
        mock_exists.return_value = True
        mock_gpu.return_value = True  # GPU available
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        # Check that usermod commands were called
        run_commands = [str(c) for c in mock_run.call_args_list]
        combined = ' '.join(run_commands)
        
        self.assertIn("usermod", combined)
        self.assertIn("video", combined)
        self.assertIn("render", combined)


class TestHardenXrdp(unittest.TestCase):
    """Test XRDP hardening."""
    
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    def test_skips_if_xrdp_not_installed(self, mock_exists, mock_run):
        """Should skip if xrdp.ini doesn't exist."""
        mock_exists.return_value = False
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        
        harden_xrdp(config)
        
        # Should not call systemctl restart
        restart_calls = [c for c in mock_run.call_args_list if 'restart' in str(c)]
        self.assertEqual(len(restart_calls), 0)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    def test_restarts_xrdp_services(self, mock_exists, mock_run):
        """Should restart xrdp and xrdp-sesman."""
        mock_exists.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        
        harden_xrdp(config)
        
        # Check that restart commands were called
        run_commands = [str(c) for c in mock_run.call_args_list]
        combined = ' '.join(run_commands)
        
        self.assertIn("systemctl restart xrdp", combined)


class TestConfigureXfceForRdp(unittest.TestCase):
    """Test XFCE RDP compatibility configuration."""
    
    @patch('desktop.desktop_environment_steps.run')
    @patch('desktop.desktop_environment_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_skips_for_non_xfce_desktop(self, mock_open, mock_makedirs, mock_run):
        """Should skip configuration for non-XFCE desktops."""
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="i3"  # Not XFCE
        )
        
        configure_xfce_for_rdp(config)
        
        # Should not create any files
        self.assertEqual(mock_open.call_count, 0)
        
    @patch('desktop.desktop_environment_steps.run')
    @patch('desktop.desktop_environment_steps.os.makedirs')
    @patch('desktop.desktop_environment_steps.os.path.exists')
    @patch('desktop.desktop_environment_steps.os.remove')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_disables_light_locker(self, mock_open, mock_remove, mock_exists, mock_makedirs, mock_run):
        """Should disable light-locker autostart."""
        mock_exists.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        configure_xfce_for_rdp(config)
        
        # Check that light-locker.desktop was written
        write_calls = [c for c in mock_open().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        self.assertIn("Light Locker", combined_content)
        self.assertIn("Hidden=true", combined_content)
        
    @patch('desktop.desktop_environment_steps.run')
    @patch('desktop.desktop_environment_steps.os.makedirs')
    @patch('desktop.desktop_environment_steps.os.path.exists')
    @patch('desktop.desktop_environment_steps.os.remove')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_disables_dpms(self, mock_open, mock_remove, mock_exists, mock_makedirs, mock_run):
        """Should disable DPMS in power manager config."""
        mock_exists.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        configure_xfce_for_rdp(config)
        
        # Check that power manager config was written
        write_calls = [c for c in mock_open().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        self.assertIn("dpms-enabled", combined_content)
        self.assertIn("false", combined_content)
        
    @patch('desktop.desktop_environment_steps.run')
    @patch('desktop.desktop_environment_steps.os.makedirs')
    @patch('desktop.desktop_environment_steps.os.path.exists')
    @patch('desktop.desktop_environment_steps.os.remove')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_creates_pm_stub(self, mock_open, mock_remove, mock_exists, mock_makedirs, mock_run):
        """Should create pm-is-supported stub to suppress warnings."""
        mock_exists.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        configure_xfce_for_rdp(config)
        
        # Check that pm-is-supported was written
        write_calls = [c for c in mock_open().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        
        self.assertIn("pm-is-supported", combined_content)
        self.assertIn("exit 1", combined_content)
        
        # Check chmod was called to make it executable
        chmod_calls = [c for c in mock_run.call_args_list if 'chmod' in str(c)]
        self.assertGreater(len(chmod_calls), 0)


if __name__ == '__main__':
    unittest.main()
