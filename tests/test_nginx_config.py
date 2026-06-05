"""Tests for lib/nginx_config.py: SSL paths and config generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.nginx_config import (
    get_ssl_cert_path,
    _make_cache_maps,
    _make_proxy_location,
    _make_static_location,
    _reconcile_deployment_sites,
    create_nginx_sites_for_groups,
    GENERATED_CONFIG_MARKER,
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

        with patch('os.path.exists', side_effect=fake_exists):
            cert, key = get_ssl_cert_path(domain)

        self.assertEqual(cert, le_cert)
        self.assertEqual(key, le_key)


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

    def test_rails_proxy_uses_backend_port_when_proxy_port_missing(self):
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

    def test_cloudflare_tunnel_disables_api_subdomain_http_redirect(self):
        deployments = [{
            'path': '/',
            'needs_proxy': True,
            'backend_port': 3007,
            'frontend_port': 5173,
            'api_subdomain': True,
        }]
        config = generate_merged_nginx_config('example.com', deployments, enable_https_redirect=False)
        self.assertNotIn('return 301 https://$host$request_uri', config)
        self.assertIn('server_name api.example.com', config)
        self.assertIn('proxy_pass http://127.0.0.1:3007', config)

    def test_cloudflare_tunnel_proxies_api_path_without_redirect(self):
        deployments = [{
            'path': '/',
            'needs_proxy': True,
            'backend_port': 3007,
            'frontend_port': 5173,
            'api_subdomain': False,
        }]
        config = generate_merged_nginx_config('example.com', deployments, enable_https_redirect=False)
        self.assertNotIn('return 301 /api/', config)
        self.assertIn('location = /api', config)
        self.assertIn('proxy_set_header X-Forwarded-Proto https', config)

    def test_standard_api_path_still_redirects_to_trailing_slash(self):
        deployments = [{
            'path': '/',
            'needs_proxy': True,
            'backend_port': 3007,
            'frontend_port': 5173,
            'api_subdomain': False,
        }]
        config = generate_merged_nginx_config('example.com', deployments)
        self.assertIn('return 301 /api/', config)
        self.assertIn('proxy_set_header X-Forwarded-Proto $scheme', config)

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
    def test_create_sites_repairs_wrong_enabled_path(self, mock_run, _mock_cert):
        with tempfile.TemporaryDirectory() as temp_dir:
            available = os.path.join(temp_dir, 'sites-available')
            enabled = os.path.join(temp_dir, 'sites-enabled')
            os.makedirs(available)
            os.makedirs(enabled)

            enabled_link = os.path.join(enabled, 'example_com')
            with open(enabled_link, 'w', encoding='utf-8') as handle:
                handle.write('stale file')

            def run_side_effect(cmd, *_args, **_kwargs):
                if cmd.startswith('ln -s '):
                    os.symlink(os.path.join(available, 'example_com'), enabled_link)
                return MagicMock(returncode=0)

            mock_run.side_effect = run_side_effect

            deployments = [{
                'path': '/',
                'needs_proxy': False,
                'serve_path': '/var/www/html',
                'project_type': 'static',
            }]

            with patch('lib.nginx_config.NGINX_SITES_AVAILABLE_DIR', available), \
                 patch('lib.nginx_config.NGINX_SITES_ENABLED_DIR', enabled):
                create_nginx_sites_for_groups({'example.com': deployments}, enable_https_redirect=False)

            self.assertTrue(os.path.islink(enabled_link))
            self.assertEqual(os.path.realpath(enabled_link), os.path.join(available, 'example_com'))


if __name__ == '__main__':
    unittest.main()
