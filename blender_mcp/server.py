"""MCP server exposing Blender to any MCP-capable agent.

Run over stdio (the normal case)::

    blender-mcp serve

Configuration comes from the environment so the same entry point works from
``uvx``, from Hermes' ``mcp_servers`` block, or from a shell::

    BLENDER_MCP_HOST           default 127.0.0.1
    BLENDER_MCP_PORT           default 9876
    BLENDER_MCP_TIMEOUT        default 120   per-command timeout, seconds
    BLENDER_MCP_CONNECT_TIMEOUT default 4    TCP connect timeout, seconds

Startup is deliberately passive: the server never opens a socket until a tool
is actually called, so MCP discovery (``initialize`` + ``tools/list``) can never
hang on an unreachable Blender.
"""

from __future__ import annotations

import json
import os
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver import Image as _Image
except ImportError:  # pragma: no cover - mcp < 2.0
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
    from mcp.server.fastmcp import Image as _Image  # type: ignore[no-redef]

from .client import BlenderClient, BlenderError, BlenderNotRunning
from mcp.types import CallToolResult, TextContent

SERVER_NAME = "blender"

INSTRUCTIONS = """\
Drive a running Blender session.

Prerequisites: Blender must be open with the "Blender MCP" add-on enabled
(3D Viewport > Sidebar > Blender MCP > Start Server), or Blender must be running
headless via `blender-mcp headless`. If a tool reports that Blender is not
reachable, tell the user to start the add-on server; do not retry in a loop.

Typical workflow: blender_status -> blender_get_scene_info -> inspect with
blender_list_objects / blender_get_object_info -> mutate with
blender_execute_code (arbitrary bpy Python) -> blender_screenshot to verify
visually -> blender_save_file.
"""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=repr)


def _error_result(message: str) -> "CallToolResult":
    """Return a tool error that actually carries the message.

    Raising from a tool makes the MCP SDK report only ``"Error executing tool
    X"`` to the client and log the real reason to stderr, which the agent never
    sees. Returning an explicit error result keeps the actionable text.
    """
    return CallToolResult(is_error=True, content=[TextContent(type="text", text=message)])


def make_client() -> BlenderClient:
    """Build the client from the current environment (called per tool use)."""
    return BlenderClient(
        host=os.environ.get("BLENDER_MCP_HOST", "127.0.0.1"),
        port=_env_int("BLENDER_MCP_PORT", 9876),
        timeout=_env_float("BLENDER_MCP_TIMEOUT", 120.0),
        connect_timeout=_env_float("BLENDER_MCP_CONNECT_TIMEOUT", 4.0),
    )


def _guarded(command: str, params: dict[str, Any]) -> Any:
    """Run a command and return either the JSON payload or a readable error."""
    try:
        return _dumps(make_client().call(command, params))
    except BlenderNotRunning as exc:
        return _error_result(str(exc))
    except BlenderError as exc:
        message = str(exc)
        detail = getattr(exc, "traceback", None)
        if detail:
            message = f"{message}\n\n{detail.strip()}"
        return _error_result(message)


def build_server() -> _Server:
    server = _Server(name=SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool(
        name="blender_status",
        description=(
            "Check whether the Blender add-on socket is reachable. Call this first. "
            "Returns {connected, host, port, blender_version, addon_version, background}."
        ),
    )
    def blender_status() -> str:
        client = make_client()
        info = client.status()
        base = {"connected": info is not None, "host": client.host, "port": client.port}
        if info is None:
            loopback = client.host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
            if loopback:
                base["hint"] = (
                    "No Blender add-on listening. Open Blender, enable the 'Blender MCP' "
                    "add-on, and press Start Server in the N-panel sidebar."
                )
            else:
                base["hint"] = (
                    f"Nothing answered on {client.host}:{client.port}. On that machine, start "
                    "Blender with the 'Blender MCP' add-on and bind it to a reachable address "
                    "(blender-mcp headless --host <tailnet-ip>, or the Host field under Add-on "
                    "Preferences) - the default 127.0.0.1 is unreachable from here. If Blender "
                    "is already running with the add-on, a firewall is dropping the port: allow "
                    "inbound TCP on it, scoped to the tailnet."
                )
            return _dumps(base)
        base.update(info)
        return _dumps(base)

    @server.tool(
        name="blender_get_scene_info",
        description=(
            "Summarise the open .blend: engine, frame range, resolution, collections, "
            "object/material counts, cameras, lights, and the object list."
        ),
    )
    def blender_get_scene_info(object_limit: int = 100):
        return _guarded("get_scene_info", {"object_limit": object_limit})

    @server.tool(
        name="blender_list_objects",
        description=(
            "List objects, optionally filtered by type ('MESH', 'CAMERA', 'LIGHT', "
            "'CURVE', 'ARMATURE', 'EMPTY', ...) or by a case-insensitive substring "
            "of the name. Returns name, type, location, dimensions, parent, visible."
        ),
    )
    def blender_list_objects(kind: str = "", name_filter: str = "", limit: int = 200):
        params: dict[str, Any] = {"limit": limit}
        if kind:
            params["kind"] = kind
        if name_filter:
            params["name_filter"] = name_filter
        return _guarded("list_objects", params)

    @server.tool(
        name="blender_get_object_info",
        description=(
            "Detailed report on one object: transform, dimensions, bounding box, "
            "mesh statistics (verts/edges/tris/UVs), material slots, modifiers, "
            "constraints, parent/children, and custom properties."
        ),
    )
    def blender_get_object_info(name: str):
        return _guarded("get_object_info", {"name": name})

    @server.tool(
        name="blender_execute_code",
        description=(
            "Run arbitrary Python inside Blender with `bpy` in scope and return "
            "{ok, result, stdout, duration_ms}. A single expression is evaluated and "
            "its value returned; otherwise the code is executed and the variable "
            "`result`, if set, is returned. This is the general-purpose escape hatch "
            "for creating and editing geometry, materials, modifiers and animation."
        ),
    )
    def blender_execute_code(code: str, timeout_s: float = 0.0):
        params: dict[str, Any] = {"code": code}
        if timeout_s:
            params["_timeout"] = timeout_s
        return _guarded("execute_code", params)

    @server.tool(
        name="blender_screenshot",
        description=(
            "Render the current scene and return it as an image, so you can see the "
            "result of your edits. Renders at max_size pixels on the long axis and "
            "restores the scene's render settings afterwards. Returns the image plus "
            "a text block naming the render strategy and lit-pixel fraction; if every "
            "strategy produced a near-black frame, the text block says so. Slow on "
            "CPU-only headless builds - prefer one screenshot at the end of a task."
        ),
    )
    def blender_screenshot(max_size: int = 1024):
        try:
            png, meta = make_client().screenshot(max_size=max_size)
        except BlenderNotRunning as exc:
            return _error_result(str(exc))
        except BlenderError as exc:
            return _error_result(str(exc))
        summary = {
            key: meta[key]
            for key in ("width", "height", "bytes", "strategy", "lit_fraction")
            if meta.get(key) is not None
        }
        text = _dumps(summary)
        if meta.get("warning"):
            text = "WARNING: " + meta["warning"] + "\n" + text
        return [_Image(data=png, format="png"), text]

    @server.tool(
        name="blender_save_file",
        description=(
            "Save the current .blend. Pass filepath to Save-As (parent directories "
            "are created), or omit it to save in place."
        ),
    )
    def blender_save_file(filepath: str = ""):
        params: dict[str, Any] = {}
        if filepath:
            params["filepath"] = filepath
        return _guarded("save_file", params)

    @server.tool(
        name="blender_get_versions",
        description="Blender version, bundled Python version, add-on version, and protocol version.",
    )
    def blender_get_versions():
        return _guarded("get_versions", {})

    return server


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    transport = "stdio"
    if argv and argv[0] in {"sse", "streamable-http"}:
        transport = argv.pop(0)
    build_server().run(transport=transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
