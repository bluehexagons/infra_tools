"""Deployment setup steps."""

from __future__ import annotations

# Import from lib modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from deploy_steps
from lib.deploy_steps import (
    setup_deployment,
    rebuild_deployment,
)

# Re-export all functions
__all__ = [
    'setup_deployment',
    'rebuild_deployment',
]
