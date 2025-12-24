#!/usr/bin/env python3

"""Validation utilities for setup scripts."""

import re


def validate_ip_address(ip: str) -> bool:
    """Validate an IPv4 address."""
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_host(host: str) -> bool:
    """Validate a hostname or IP address."""
    normalized_host = host.lower().rstrip('.')
    if validate_ip_address(normalized_host):
        return True
    hostname_pattern = r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
    return bool(re.match(hostname_pattern, normalized_host))


def validate_username(username: str) -> bool:
    """Validate a Unix username."""
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))
