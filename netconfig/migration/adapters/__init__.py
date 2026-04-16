"""Vendor-adapter package.  Each sub-module registers its adapter."""

from .base import AdapterBase, AdapterError, ParseError, RenderError
from .registry import get_adapter, list_adapters, register

__all__ = [
    "AdapterBase",
    "AdapterError",
    "ParseError",
    "RenderError",
    "get_adapter",
    "list_adapters",
    "register",
]
