"""Blender MCP: expose a running Blender session to MCP-capable agents."""

from .client import BlenderClient, BlenderError, BlenderNotRunning
from .protocol import DEFAULT_HOST, DEFAULT_PORT, PROTOCOL_VERSION

__version__ = "1.0.0"

__all__ = [
    "BlenderClient",
    "BlenderError",
    "BlenderNotRunning",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "PROTOCOL_VERSION",
    "__version__",
]
