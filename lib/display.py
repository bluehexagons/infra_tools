#!/usr/bin/env python3

from lib.config import SetupConfig


def print_name_and_tags(config: SetupConfig) -> None:
    if config.friendly_name:
        print(f"Name: {config.friendly_name}")
    if config.tags and len(config.tags) > 0:
        print(f"Tags: {', '.join(config.tags)}")


def print_success_header(config: SetupConfig) -> None:
    print(f"Host: {config.host}")
    print(f"Username: {config.username}")
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)


def print_rdp_x2go_info(config: SetupConfig) -> None:
    if config.enable_rdp:
        print(f"RDP: {config.host}:3389")
        print(f"  Client: Remmina, Microsoft Remote Desktop")
    if config.enable_x2go:
        print(f"X2Go: {config.host}:22 (SSH)")
        print(f"  Client: x2goclient, Session: XFCE")
