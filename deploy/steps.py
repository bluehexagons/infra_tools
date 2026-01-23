"""Deployment setup steps."""

from __future__ import annotations

# Import from lib modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from deploy_steps
from lib.deploy_steps import (
    ensure_app_user,
    deploy_repository,
)

# Re-export all functions
__all__ = [
    'ensure_app_user',
    'deploy_repository',
]
