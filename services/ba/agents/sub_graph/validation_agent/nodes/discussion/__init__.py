"""Discussion node package."""

from .callback import va_discuss_after_callback, va_discuss_inject_callback
from .node import create_va_discuss_node

__all__ = [
    "create_va_discuss_node",
    "va_discuss_after_callback",
    "va_discuss_inject_callback",
]
