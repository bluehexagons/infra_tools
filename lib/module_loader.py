"""Module loading system for infra_tools.

This module provides a centralized way to import steps and utilities from
various modules without hardcoding import paths.
"""

from __future__ import annotations

import importlib
import sys
import os
from typing import Callable, Dict, Any

# Add the base directory to sys.path if not already present
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def get_module_steps(module_name: str) -> Dict[str, Callable[..., Any]]:
    """Import and return all step functions from a module's steps.py.
    
    Args:
        module_name: Name of the module (e.g., 'desktop', 'web', 'smb')
        
    Returns:
        Dictionary mapping step function names to functions
    """
    try:
        steps_module = importlib.import_module(f"{module_name}.steps")
        
        # Get all functions from the module that don't start with _
        steps = {}
        for name in dir(steps_module):
            if not name.startswith('_'):
                attr = getattr(steps_module, name)
                if callable(attr):
                    steps[name] = attr
        
        return steps
    except ImportError as e:
        print(f"Warning: Could not import {module_name}.steps: {e}")
        return {}


def import_from_module(module_name: str, *names: str) -> Dict[str, Any]:
    """Import specific items from a module.
    
    Args:
        module_name: Full module path (e.g., 'desktop.steps')
        *names: Names to import from the module
        
    Returns:
        Dictionary mapping names to imported objects
    """
    try:
        module = importlib.import_module(module_name)
        result = {}
        for name in names:
            if hasattr(module, name):
                result[name] = getattr(module, name)
            else:
                print(f"Warning: {module_name} does not have {name}")
        return result
    except ImportError as e:
        print(f"Warning: Could not import from {module_name}: {e}")
        return {}
