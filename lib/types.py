"""Common type aliases for the project to reduce repetition and improve readability.

Add new aliases here when you spot repeated typing patterns across modules.
"""
from __future__ import annotations

from typing import Any, Optional, Callable, Union, Literal, TypeVar 
from collections import deque
from pathlib import Path

# Basic JSON types
JSON = Any
JSONDict = dict[str, Any]
JSONList = list[JSON]

# String-based types
StrList = list[str]
StrDict = dict[str, str]
NestedStrList = list[list[str]]
StrSet = set[str]

# Optional types
MaybeStr = Optional[str]
MaybeInt = Optional[int]
MaybeBool = Optional[bool]
MaybePath = Optional[Path]

# Path and file types
PathList = list[Path]
PathStr = Union[str, Path]
PathPair = tuple[str, str]

# Collection types
IntList = list[int]
BoolList = list[bool]
IntDict = dict[str, int]
BoolDict = dict[str, bool]

# Project-specific types
Deployments = list[JSONDict]
StepFunc = Callable[..., Any]
AnyCallable = Callable[..., Any]
DequeAny = deque[Any]

# Generic type variables
T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')

# Generic collection types
DictStr = dict[str, V]
ListAny = list[T]
Maybe = Optional[T]

# System type literals
SystemType = Literal[
    "workstation_desktop",
    "pc_dev", 
    "workstation_dev",
    "server_dev",
    "server_web",
    "server_lite",
    "server_proxmox",
    "custom_steps"
]

DesktopType = Literal["xfce", "gnome", "kde"]

__all__ = [
    # Basic JSON types
    "JSON",
    "JSONDict", 
    "JSONList",
    
    # String-based types
    "StrList",
    "StrDict",
    "NestedStrList",
    "StrSet",
    
    # Optional types
    "MaybeStr",
    "MaybeInt",
    "MaybeBool",
    "MaybePath",
    
    # Path and file types
    "PathList",
    "PathStr",
    "PathPair",
    
    # Collection types
    "IntList",
    "BoolList", 
    "IntDict",
    "BoolDict",
    
    # Project-specific types
    "Deployments",
    "StepFunc",
    "AnyCallable",
    "DequeAny",
    
    # Generic type variables
    "T",
    "K",
    "V",
    
    # Generic collection types
    "DictStr",
    "ListAny",
    "Maybe",
    
    # System type literals
    "SystemType",
    "DesktopType",
]
