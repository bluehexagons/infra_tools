"""Tests for lib/nginx_config.py: SSL paths and config generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.nginx_config import (
    certificate_is_usable,
    get_ssl_cert_path,
    _make_cache_maps,
    _make_proxy_location,
    _make_static_location,
    _reconcile_deployment_sites,
    create_nginx_sites_for_groups,
    GENERATED_CONFIG_MARKER,
    generate_self_signed_cert,
    generate_merged_nginx_config,
    SSL_PROTOCOLS,
)


class TestGetSslCertPath(unittest.TestCase):
    def test_no_domain(self):
        cert, key = get_ssl_cert_path(None)
        self.assertIn('default', cert)
        self.assertIn('default', key)

    def test_domain_no_letsencrypt(self):
        cert, key = get_ssl_cert_path('example.com')
        self.assertIn('example.com', cert)
        self.assertIn('example.com', key)
        self.assertTrue(cert.endswith('.crt'))
        self.assertTrue(key.endswith('.key'))

    def test_letsencrypt_exists(self):
        domain = 'example.com'
        le_cert = f'/etc/letsencrypt/live/{domain}/fullchain.pem'
        le_key = f'/etc/letsencrypt/live/{domain}/privkey.pem'

        real_exists = os.path.exists

        def fake_exists(path):
            if path in (le_cert, le_key):
                return True
            return real_exists(path)

        with (
            patch('os.path.exists', side_effect=fake_exists),
            patch('lib.nginx_config.certificate_is_usable', return_value=True),
        ):
            cert, key = get_ssl_cert_path(domain)

        self.assertEqual(cert, le_cert)
        self.assertEqual(key, le_key)

    @patch("lib.nginx_config.certificate_is_usable", return_value=True)
    @patch("lib.nginx_config.run")
    @patch("lib.nginx_config.os.path.exists", return_value=False)
    def test_self_signed_ip_certificate_includes_ip_san(
        self, _exists, mock_run, _usable
    ):
        generate_self_signed_cert("192.168.0.51")

        command = mock_run.call_args_list[-1].args[0]
        self.assertIn("-subj /CN=192.168.0.51", command)
        self.assertIn("-addext subjectAltName=IP:192.168.0.51", command)

    @patch("lib.nginx_config.certificate_is_usable", return_value=True)
    @patch("lib.nginx_config.run")
    @patch("lib.nginx_config.os.path.exists", return_value=False)
    def test_self_signed_domain_certificate_includes_dns_san(
        self, _exists, mock_run, _usable
    ):
        generate_self_signed_cert("git.example.test")

        command = mock_run.call_args_list[-1].args[0]
        self.assertIn("-addext subjectAltName=DNS:git.example.test", command)

    @patch("lib.nginx_config.certificate_is_usable", return_value=True)
    @patch("lib.nginx_config.run")
    @patch("lib.nginx_config.os.path.exists", return_value=False)
    def test_self_signed_certificate_includes_additional_ip_san(
        self, _exists, mock_run, _usable
    ):
        generate_self_signed_cert("192.168.0.51", ["127.0.0.1"])

        command = mock_run.call_args_list[-1].args[0]
        self.assertIn(
            "-addext subjectAltName=IP:192.168.0.51,IP:127.0.0.1",
            command,
        )

    @patch("lib.nginx_config.certificate_is_usable", side_effect=[False, True])
    @patch("lib.nginx_config.run")
    @patch("lib.nginx_config.os.path.exists", return_value=True)
    def test_expiring_self_signed_certificate_is_replaced(
        self, _exists, mock_run, _usable
    ):
        generate_self_signed_cert("192.168.0.51")

        self.assertTrue(any("openssl req -x509" in call.args[0] for call in mock_run.call_args_list))


class TestCertificateIsUsable(unittest.TestCase):
    @patch("lib.nginx_config.run")
    def test_ip_identity_uses_openssl_checkip(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="digest\n"),
            MagicMock(returncode=0, stdout="digest\n"),
        ]

        self.assertTrue(
            certificate_is_usable("cert.pem", "key.pem", ["192.168.0.51"])
        )
        self.assertIn("-checkip 192.168.0.51", mock_run.call_args_list[1].args[0])


class TestMakeCacheMaps(unittest.TestCase):
    def test_returns_maps_and_vars(self):
        maps, expires_var, cc_var = _make_cache_maps('example_com')
        self.assertIn('example_com', expires_var)
        self.assertIn('example_com', cc_var)
        self.assertIn('map', maps)
        self.assertIn('css', maps)
        self.assertIn('js', maps)


class TestMakeProxyLocation(unittest.TestCase):
    def test_root_location(self):
        result = _make_proxy_location('/', 3000, '# Backend')
        self.assertIn('proxy_pass http://127.0.0.1:3000', result)
        self.assertIn('location /', result)

    def test_subpath_location(self):
        result = _make_proxy_location('/api', 4000, '# API')
        self.assertIn('proxy_pass http://127.0.0.1:4000/', result)
        self.assertIn('location /api/', result)
        self.assertIn('return 301 /api/', result)

    def test_websocket_support(self):
        result = _make_proxy_location('/', 3000, '# WS', enable_websocket=True)
        self.assertIn('Upgrade', result)
        self.assertIn('upgrade', result)

    def test_subpath_location_can_proxy_exact_path_without_redirect(self):
        result = _make_proxy_location('/api', 4000, '# API', forwarded_proto='https', enable_path_redirect=False)
        self.assertIn('location = /api', result)
        self.assertIn('proxy_pass http://127.0.0.1:4000/', result)
        self.assertIn('proxy_set_header X-Forwarded-Proto https', result)
        self.assertNotIn('return 301 /api/', result)


class TestMakeStaticLocation(unittest.TestCase):
    def test_root_static(self):
        result = _make_static_location('/', '/var/www/html', 'index.html', '$uri =404', '# Static')
        self.assertIn('root /var/www/html', result)
        self.assertIn('location /', result)

    def test_subpath_static(self):
        result = _make_static_location('/blog', '/var/www/blog/', 'index.html', '$uri =404', '# Blog')
        self.assertIn('alias /var/www/blog/', result)
        self.assertIn('location /blog', result)


class TestGenerateMergedNginxConfig(unittest.TestCase):
    def test_basic_static_config(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn(GENERATED_CONFIG_MARKER, config)
        self.assertIn('server_name example.com', config)
        self.assertIn('listen 80', config)
        self.assertIn('listen 443 ssl', config)
        self.assertIn(SSL_PROTOCOLS, config)

    def test_no_domain(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config(None, deployments, is_default=True)
        self.assertIn('server_name _', config)
        self.assertIn('default_server', config)

    def test_proxy_config(self):
        deployments = [{
            'path': '/',
            'needs_proxy': True,
            'proxy_port': 3000,
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('proxy_pass', config)

    def test_proxy_uses_backend_port_when_proxy_port_missing(self):
        deployments = [{
            'path': '/',
            'needs_proxy': True,
            'backend_port': 3007,
            'frontend_port': None,
            'frontend_serve_path': None,
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('proxy_pass http://127.0.0.1:3007', config)

    def test_hidden_files_denied(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('deny all', config)

    def test_acme_challenge(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('acme-challenge', config)

    def test_http2_directive_not_deprecated(self):
        """http2 should use the standalone directive, not the deprecated listen parameter."""
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertNotIn('listen 443 ssl http2', config)
        self.assertNotIn('listen [::]:443 ssl http2', config)
        self.assertIn('http2 on', config)


    def test_http_redirects_to_https(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('return 301 https://$host$request_uri', config)
        # ACME challenge must remain reachable on plaintext HTTP for renewals.
        http_block_end = config.find('}', config.find('listen 80'))
        http_block = config[: http_block_end]
        self.assertIn('acme-challenge', http_block)

    def test_cloudflare_tunnel_disables_http_https_redirect(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments, enable_https_redirect=False)
        self.assertNotIn('return 301 https://$host$request_uri', config)
        http_block_end = config.find('server {\n    listen 443 ssl')
        http_block = config[: http_block_end]
        self.assertIn('root /var/www/html', http_block)
        self.assertIn('acme-challenge', http_block)

    def test_hsts_header_present(self):
        deployments = [{
            'path': '/',
            'needs_proxy': False,
            'serve_path': '/var/www/html',
            'project_type': 'static',
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('Strict-Transport-Security', config)
        self.assertIn('max-age=63072000', config)


class TestReconcileDeploymentSites(unittest.TestCase):
    def test_preserves_legacy_rails_site_owned_by_existing_unit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            available = os.path.join(temp_dir, 'sites-available')
            enabled = os.path.join(temp_dir, 'sites-enabled')
            os.makedirs(available)
            os.makedirs(enabled)
            legacy_site = os.path.join(available, 'legacy_example_com')
            with open(legacy_site, 'w', encoding='utf-8') as handle:
                handle.write(f"{GENERATED_CONFIG_MARKER}\n")

            with patch('lib.nginx_config.NGINX_SITES_AVAILABLE_DIR', available), \
                 patch('lib.nginx_config.NGINX_SITES_ENABLED_DIR', enabled), \
                 patch('lib.nginx_config._is_legacy_rails_site', return_value=True):
                _reconcile_deployment_sites(set())

            self.assertTrue(os.path.exists(legacy_site))

    def test_removes_stale_deployment_sites_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            available = os.path.join(temp_dir, 'sites-available')
            enabled = os.path.join(temp_dir, 'sites-enabled')
            os.makedirs(available)
            os.makedirs(enabled)

            names = (
                'current_com', 'api_old_com', 'default',
                'antistatic_game_com', 'gogs_git_com', 'manual_site',
            )
            legacy_generated = """
map $uri $assets_expires_api_old_com {
}
map $uri $assets_cc_api_old_com {
}
server {
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }
    add_header Strict-Transport-Security "max-age=63072000" always;
}
"""
            for directory in (available, enabled):
                for name in names:
                    with open(os.path.join(directory, name), 'w', encoding='utf-8') as handle:
                        handle.write(legacy_generated if name == 'api_old_com' else name)

            old_link = os.path.join(enabled, 'old_link_com')
            os.symlink(os.path.join(available, 'api_old_com'), old_link)

            with patch('lib.nginx_config.NGINX_SITES_AVAILABLE_DIR', available), \
                 patch('lib.nginx_config.NGINX_SITES_ENABLED_DIR', enabled):
                _reconcile_deployment_sites({'current_com', 'default'})

            for directory in (available, enabled):
                self.assertTrue(os.path.exists(os.path.join(directory, 'current_com')))
                self.assertTrue(os.path.exists(os.path.join(directory, 'default')))
                self.assertTrue(os.path.exists(os.path.join(directory, 'antistatic_game_com')))
                self.assertTrue(os.path.exists(os.path.join(directory, 'gogs_git_com')))
                self.assertTrue(os.path.exists(os.path.join(directory, 'manual_site')))
                self.assertFalse(os.path.lexists(os.path.join(directory, 'api_old_com')))
            self.assertFalse(os.path.lexists(old_link))

    @patch('lib.nginx_config.generate_self_signed_cert')
    @patch('lib.nginx_config.run')
    def test_create_sites_refuses_unmanaged_same_name(self, mock_run, _mock_cert):
        with tempfile.TemporaryDirectory() as temp_dir:
            available = os.path.join(temp_dir, 'sites-available')
            enabled = os.path.join(temp_dir, 'sites-enabled')
            os.makedirs(available)
            os.makedirs(enabled)

            enabled_link = os.path.join(enabled, 'example_com')
            with open(enabled_link, 'w', encoding='utf-8') as handle:
                handle.write('stale file')

            deployments = [{
                'path': '/',
                'needs_proxy': False,
                'serve_path': '/var/www/html',
                'project_type': 'static',
            }]

            with patch('lib.nginx_config.NGINX_SITES_AVAILABLE_DIR', available), \
                 patch('lib.nginx_config.NGINX_SITES_ENABLED_DIR', enabled):
                with self.assertRaisesRegex(RuntimeError, 'unmanaged Nginx'):
                    create_nginx_sites_for_groups(
                        {'example.com': deployments}, enable_https_redirect=False
                    )

            self.assertFalse(os.path.islink(enabled_link))
            with open(enabled_link, 'r', encoding='utf-8') as handle:
                self.assertEqual(handle.read(), 'stale file')
            mock_run.assert_not_called()

    @patch('lib.nginx_config.generate_self_signed_cert')
    @patch('lib.nginx_config.run')
    def test_create_sites_restores_previous_files_when_validation_fails(
        self, mock_run, _mock_cert
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            available = os.path.join(temp_dir, 'sites-available')
            enabled = os.path.join(temp_dir, 'sites-enabled')
            os.makedirs(available)
            os.makedirs(enabled)
            config_path = os.path.join(available, 'example_com')
            previous = f"{GENERATED_CONFIG_MARKER}\n# previous\n"
            with open(config_path, 'w', encoding='utf-8') as handle:
                handle.write(previous)
            os.symlink(config_path, os.path.join(enabled, 'example_com'))

            validations = iter((1, 0))

            def run_side_effect(command, *_args, **_kwargs):
                if command == 'nginx -t':
                    return MagicMock(returncode=next(validations))
                return MagicMock(returncode=0)

            mock_run.side_effect = run_side_effect
            deployments = [{
                'path': '/',
                'needs_proxy': False,
                'serve_path': '/var/www/new',
                'project_type': 'static',
            }]

            with patch('lib.nginx_config.NGINX_SITES_AVAILABLE_DIR', available), \
                 patch('lib.nginx_config.NGINX_SITES_ENABLED_DIR', enabled):
                with self.assertRaisesRegex(RuntimeError, 'configuration test'):
                    create_nginx_sites_for_groups(
                        {'example.com': deployments},
                        enable_https_redirect=False,
                    )

            with open(config_path, 'r', encoding='utf-8') as handle:
                self.assertEqual(handle.read(), previous)
            self.assertTrue(os.path.islink(os.path.join(enabled, 'example_com')))


if __name__ == '__main__':
    unittest.main()
