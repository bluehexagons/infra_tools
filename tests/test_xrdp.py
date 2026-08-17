"""Tests for XRDP configuration functions."""

from __future__ import annotations
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from lib.config import SetupConfig
from desktop.xrdp_steps import (
    _ensure_user_in_group,
    _generate_sesman_ini,
    _generate_xrdp_ini,
    _generate_xorg_conf,
    _configure_xrdp_socket_environment,
    _validate_xrdp_tls_certificate,
    harden_xrdp,
    install_xrdp,
)
from desktop.desktop_environment_steps import configure_xfce_for_rdp, install_desktop
from lib.xrdp_certificate import XrdpCertificateHealth


class TestGenerateSesmanIni(unittest.TestCase):
    """Test sesman.ini generation."""

    def setUp(self):
        self.config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
        )
    
    def test_generates_valid_ini_format(self):
        """sesman.ini should have proper INI sections."""
        result = _generate_sesman_ini(self.config)
        
        # Check required sections exist
        self.assertIn("[Globals]", result)
        self.assertIn("[Security]", result)
        self.assertIn("[Sessions]", result)
        self.assertIn("[Logging]", result)
        self.assertIn("[Xorg]", result)
        
    def test_uses_xorg_backend_only(self):
        """Should use Xorg backend, not Xvnc."""
        result = _generate_sesman_ini(self.config)
        
        # Xorg section should exist
        self.assertIn("[Xorg]", result)
        self.assertIn("param=/usr/lib/xorg/Xorg", result)
        self.assertIn("param=xrdp/xorg.conf", result)
        self.assertNotIn("param=/etc/X11/xrdp/xorg.conf", result)
        self.assertIn("param=.local/share/xorg/Xorg.%s.log", result)
        self.assertNotIn("param=.xorgxrdp.%s.log", result)
        
        # Xvnc section should NOT exist
        self.assertNotIn("[Xvnc]", result)
        self.assertNotIn("Xvnc", result)
        
    def test_does_not_include_unsupported_end_session_command(self):
        result = _generate_sesman_ini(self.config)

        self.assertNotIn("EndSessionCommand", result)
        
    def test_security_settings(self):
        """Should include security restrictions."""
        result = _generate_sesman_ini(self.config)
        
        # Security settings
        self.assertIn("AllowRootLogin=false", result)
        self.assertIn("TerminalServerUsers=remoteusers", result)
        self.assertIn("AlwaysGroupCheck=true", result)

    def test_renders_native_session_lifecycle_policy(self):
        self.config.rdp_max_sessions = 2
        self.config.rdp_kill_disconnected = True
        self.config.rdp_disconnected_timeout = 86400
        self.config.rdp_idle_timeout = 14400

        result = _generate_sesman_ini(self.config)

        self.assertIn("MaxSessions=2", result)
        self.assertIn("KillDisconnected=true", result)
        self.assertIn("DisconnectedTimeLimit=86400", result)
        self.assertIn("IdleTimeLimit=14400", result)


class TestGenerateXrdpIni(unittest.TestCase):
    def test_project_template_renders_without_policy_placeholders(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "desktop"
            / "config"
            / "xrdp.ini.template"
        )
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
        )

        rendered = _generate_xrdp_ini(config, template_path.read_text(encoding="utf-8"))

        self.assertNotIn("{RDP_", rendered)
        self.assertIn("[Channels]", rendered)
        self.assertIn("drdynvc=true", rendered)
        self.assertIn("rdpdr=false", rendered)
        self.assertIn("rail=false", rendered)
        self.assertIn("xrdpvr=false", rendered)
        self.assertIn("certificate=/etc/xrdp/cert.pem", rendered)
        self.assertIn("key_file=/etc/xrdp/key.pem", rendered)
        self.assertNotIn("channel_code", rendered)
        xorg_section = rendered.split("[Xorg]\n", 1)[1]
        self.assertNotIn("\nip=", xorg_section)

    def test_renders_listener_and_secure_coding_channel_defaults(self):
        template = (
            "address={RDP_BIND_ADDRESS}\n"
            "rdpdr={RDP_DRIVE_REDIRECTION}\n"
            "rdpsnd={RDP_AUDIO}\n"
            "cliprdr={RDP_CLIPBOARD}\n"
        )
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
        )

        rendered = _generate_xrdp_ini(config, template)

        self.assertIn("address=0.0.0.0", rendered)
        self.assertIn("rdpdr=false", rendered)
        self.assertIn("rdpsnd=false", rendered)
        self.assertIn("cliprdr=true", rendered)

    def test_renders_explicit_channel_policy(self):
        template = (
            "address={RDP_BIND_ADDRESS}\n"
            "rdpdr={RDP_DRIVE_REDIRECTION}\n"
            "rdpsnd={RDP_AUDIO}\n"
            "cliprdr={RDP_CLIPBOARD}\n"
        )
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            rdp_bind_address="10.0.0.25",
            rdp_clipboard=False,
            rdp_drive_redirection=True,
            rdp_audio=True,
        )

        rendered = _generate_xrdp_ini(config, template)

        self.assertIn("address=10.0.0.25", rendered)
        self.assertIn("rdpdr=true", rendered)
        self.assertIn("rdpsnd=true", rendered)
        self.assertIn("cliprdr=false", rendered)


class TestEnsureUserInGroup(unittest.TestCase):
    """Test xRDP group membership helper."""

    @patch('desktop.xrdp_steps.run')
    def test_returns_false_when_adduser_fails(self, mock_run):
        """Should not report a change if adduser fails."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout="", stderr=""),
            Mock(returncode=1, stdout="", stderr="permission denied"),
        ]

        result = _ensure_user_in_group("xrdp", "ssl-cert")

        self.assertFalse(result)

    @patch('desktop.xrdp_steps.run')
    def test_returns_true_only_after_verified_membership_change(self, mock_run):
        """Should verify membership after a successful add."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
        ]

        result = _ensure_user_in_group("xrdp", "ssl-cert")

        self.assertTrue(result)

    @patch('desktop.xrdp_steps.run')
    def test_returns_false_when_membership_cannot_be_verified(self, mock_run):
        """Should not report a change if membership cannot be verified after adduser."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=1, stdout="", stderr=""),
        ]

        result = _ensure_user_in_group("xrdp", "ssl-cert")

        self.assertFalse(result)


class TestValidateXrdpTlsCertificate(unittest.TestCase):
    @patch("desktop.xrdp_steps.inspect_xrdp_certificate_pair")
    def test_accepts_healthy_or_expiring_pair(self, mock_inspect):
        mock_inspect.return_value = XrdpCertificateHealth(
            "warning",
            "/etc/xrdp/cert.pem",
            "/etc/xrdp/key.pem",
            ("certificate expires soon",),
        )

        _validate_xrdp_tls_certificate()

    @patch("desktop.xrdp_steps.run")
    @patch("desktop.xrdp_steps.inspect_xrdp_certificate_pair")
    def test_rejects_unusable_pair(self, mock_inspect, mock_run):
        mock_inspect.return_value = XrdpCertificateHealth(
            "error",
            "/etc/xrdp/cert.pem",
            "/etc/xrdp/key.pem",
            ("private key is unreadable",),
        )

        with self.assertRaisesRegex(RuntimeError, "certificate validation failed"):
            _validate_xrdp_tls_certificate()

        mock_run.assert_called_once_with(
            "systemctl stop xrdp xrdp-sesman", check=False
        )


class TestInstallXrdp(unittest.TestCase):
    """Test XRDP installation and configuration."""

    def setUp(self):
        certificate_patcher = patch(
            "desktop.xrdp_steps._validate_xrdp_tls_certificate"
        )
        self.addCleanup(certificate_patcher.stop)
        certificate_patcher.start()
        package_patcher = patch(
            "desktop.xrdp_steps.is_package_installed",
            return_value=True,
        )
        self.addCleanup(package_patcher.stop)
        package_patcher.start()
        home_patcher = patch(
            "desktop.xrdp_steps.get_user_home",
            return_value="/home/testuser",
        )
        self.addCleanup(home_patcher.stop)
        home_patcher.start()

    @patch("desktop.xrdp_steps.run")
    def test_fails_when_xrdp_package_install_fails(self, mock_run):
        mock_run.return_value = Mock(returncode=100, stdout="", stderr="apt failed")
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce",
        )

        with self.assertRaisesRegex(RuntimeError, "xRDP package installation failed"):
            install_xrdp(config)


    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.is_service_active')
    def test_installs_required_packages(self, mock_is_active, mock_open, mock_makedirs, mock_exists, mock_run):
        """Should install xrdp, xorgxrdp, and utilities."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
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
    @patch('desktop.xrdp_steps.is_service_active')
    def test_creates_xwrapper_config(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should create /etc/X11/Xwrapper.config with correct content."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
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
    @patch('desktop.xrdp_steps.is_service_active')
    def test_creates_apparmor_compatible_xorg_log_directory(
        self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run
    ):
        """Rootless Xorg should log in the path allowed by Debian AppArmor."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce",
        )

        install_xrdp(config)

        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(
            "runuser -u testuser -- mkdir -p /home/testuser/.local/share/xorg",
            run_commands,
        )
        self.assertIn("chmod 700 /home/testuser/.local/share/xorg", run_commands)

    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_configures_app_armor_compatible_socket_environment(
        self, mock_open_func, mock_makedirs, mock_run
    ):
        """Both XRDP daemons should pass the socket path to rootless Xorg."""
        _configure_xrdp_socket_environment()

        written = "".join(
            call.args[0] for call in mock_open_func().write.call_args_list
        )
        self.assertEqual(written.count("Environment=XRDP_SOCKET_PATH=/run/xrdp/sockdir"), 2)
        self.assertEqual(mock_run.call_args_list[0].args[0], "systemctl daemon-reload")
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.is_service_active')
    def test_writes_sesman_ini(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should write sesman.ini with Xorg backend."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
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
    @patch('desktop.xrdp_steps.is_service_active')
    def test_creates_xorg_conf_with_correct_settings(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """X.Org config should have correct driver and screen size."""
        def exists_side_effect(path):
            if path == "/etc/X11/xrdp/xorg.conf.bak":
                return False
            return True

        mock_exists.side_effect = exists_side_effect
        mock_is_active.return_value = True
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

        self.assertIn(
            'cp /etc/X11/xrdp/xorg.conf /etc/X11/xrdp/xorg.conf.bak',
            [call.args[0] for call in mock_run.call_args_list],
        )

    def test_generated_xorg_conf_has_managed_resize_settings(self):
        content = _generate_xorg_conf()

        self.assertIn('Driver "xrdpdev"', content)
        self.assertIn('Option "UseGlamor" "false"', content)
        self.assertIn('Modes "640x480" "800x600" "1024x768"', content)
        self.assertIn('Virtual 3840 2160', content)

    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='exec {SESSION_CMD}\n')
    @patch('desktop.xrdp_steps.is_service_active')
    def test_uses_lxqt_session_command(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """LXQt RDP sessions should start LXQt, not fall back to XFCE."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="lxqt"
        )

        install_xrdp(config)

        write_calls = [c for c in mock_open_func().write.call_args_list]
        combined_content = ''.join([str(c[0][0]) for c in write_calls if c[0]])
        self.assertIn("exec startlxqt", combined_content)
        self.assertIn("XRDP_SOCKET_PATH=/run/xrdp/sockdir", combined_content)
        self.assertNotIn("exec xfce4-session", combined_content)
        
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.is_service_active')
    def test_does_not_grant_gpu_groups_for_software_xrdp(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """The xrdpdev software path does not require DRM device access."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )
        
        install_xrdp(config)
        
        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertFalse(any("usermod" in command for command in run_commands))
        self.assertFalse(any("group video" in command for command in run_commands))
        self.assertFalse(any("group render" in command for command in run_commands))

    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('desktop.xrdp_steps.is_service_active')
    def test_refreshes_xrdp_services_once_after_configuration(self, mock_is_active, mock_open_func, mock_makedirs, mock_exists, mock_run):
        """Should refresh xrdp services once after writing configuration."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )

        install_xrdp(config)

        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("systemctl reload-or-restart xrdp-sesman xrdp", run_commands)
        self.assertNotIn("systemctl restart xrdp-sesman", run_commands)
        self.assertNotIn("systemctl restart xrdp", run_commands)


class TestInstallDesktop(unittest.TestCase):
    @patch("desktop.desktop_environment_steps.install_package", return_value=False)
    @patch("desktop.desktop_environment_steps.is_package_installed", return_value=False)
    def test_fails_when_desktop_package_install_fails(self, _mock_installed, _mock_install):
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce",
        )

        with self.assertRaisesRegex(RuntimeError, "desktop installation failed"):
            install_desktop(config)


class TestHardenXrdp(unittest.TestCase):
    """Test XRDP hardening."""
    
    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.is_service_active')
    def test_skips_if_xrdp_not_installed(self, mock_is_active, mock_exists, mock_run):
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
    @patch('desktop.xrdp_steps.is_service_active')
    def test_refreshes_xrdp_services_when_ssl_cert_membership_changes(self, mock_is_active, mock_exists, mock_run):
        """Should refresh xrdp services if ssl-cert access changes."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        membership_results = iter([1, 0])

        def run_side_effect(cmd, **kwargs):
            if cmd.startswith("id -nG xrdp"):
                return Mock(returncode=next(membership_results), stdout="", stderr="")
            return Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect
        
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )
        
        harden_xrdp(config)
        
        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("getent group ssl-cert && adduser xrdp ssl-cert", run_commands)
        self.assertIn("systemctl reload-or-restart xrdp-sesman xrdp", run_commands)

    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.is_service_active')
    def test_skips_service_refresh_when_already_hardened(self, mock_is_active, mock_exists, mock_run):
        """Should skip reloading active services when ssl-cert access already exists."""
        mock_exists.return_value = True
        mock_is_active.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )

        harden_xrdp(config)

        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertFalse(any("reload-or-restart" in command for command in run_commands))
        self.assertFalse(any(command.startswith("systemctl start ") for command in run_commands))

    @patch('desktop.xrdp_steps.run')
    @patch('desktop.xrdp_steps.os.path.exists')
    @patch('desktop.xrdp_steps.is_service_active')
    def test_skips_service_refresh_when_ssl_cert_add_fails(self, mock_is_active, mock_exists, mock_run):
        """Should not refresh running services if ssl-cert membership was not changed."""
        mock_exists.return_value = True
        mock_is_active.return_value = True

        def run_side_effect(cmd, **kwargs):
            if cmd.startswith("id -nG xrdp"):
                return Mock(returncode=1, stdout="", stderr="")
            if cmd == "getent group ssl-cert && adduser xrdp ssl-cert":
                return Mock(returncode=1, stdout="", stderr="permission denied")
            return Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev"
        )

        harden_xrdp(config)

        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("getent group ssl-cert && adduser xrdp ssl-cert", run_commands)
        self.assertFalse(any("reload-or-restart" in command for command in run_commands))
        self.assertFalse(any(command.startswith("systemctl start ") for command in run_commands))


class TestConfigureXfceForRdp(unittest.TestCase):
    """Test XFCE RDP compatibility configuration."""

    def setUp(self):
        home_patcher = patch(
            "desktop.desktop_environment_steps.get_user_home",
            return_value="/home/testuser",
        )
        self.addCleanup(home_patcher.stop)
        home_patcher.start()
    
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
    def test_removes_stale_display_workarounds(self, mock_open, mock_remove, mock_exists, mock_makedirs, mock_run):
        """Should remove stale display profile and legacy xfsettingsd override."""
        mock_exists.return_value = True
        mock_run.return_value = Mock(returncode=0)

        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_dev",
            desktop="xfce"
        )

        configure_xfce_for_rdp(config)

        removed_paths = [call.args[0] for call in mock_remove.call_args_list]
        self.assertIn("/home/testuser/.config/autostart/xfsettingsd.desktop", removed_paths)
        self.assertIn("/home/testuser/.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml", removed_paths)
        
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
