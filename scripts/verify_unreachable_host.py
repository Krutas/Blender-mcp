#!/usr/bin/env python3
"""Prove the unbounded-connect failure mode cannot happen here.

Points the MCP server at a host whose port is *firewalled* (SYN dropped, not
refused) -- the case that makes a naive Blender MCP server hang for the OS TCP
timeout during discovery, so no tools ever load.

Expected: discovery completes in well under a second, all tools register, and a
tool call fails fast with a readable message instead of hanging.

    python scripts/verify_unreachable_host.py [--host 192.0.2.10] [--port 9876]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

#: Discovery must finish far inside this. Anything near the OS TCP timeout
#: (~2 minutes) means the connect is unbounded and the bug is back.
DISCOVERY_BUDGET_S = 10.0


async def run(host: str, port: int) -> int:
    env = {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")},
        "BLENDER_MCP_HOST": host,
        "BLENDER_MCP_PORT": str(port),
        "BLENDER_MCP_CONNECT_TIMEOUT": "4",
        "BLENDER_MCP_TIMEOUT": "30",
    }
    params = StdioServerParameters(command=PYTHON, args=["-m", "blender_mcp", "serve"], env=env, cwd=str(REPO))

    failures = []

    def check(name, ok, detail=""):
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    print(f"target: {host}:{port} (expected unreachable / SYN-dropped)")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            started = time.monotonic()
            await session.initialize()
            listed = await session.list_tools()
            discovery = time.monotonic() - started
            check(
                f"discovery completed in {discovery:.2f}s (budget {DISCOVERY_BUDGET_S}s)",
                discovery < DISCOVERY_BUDGET_S,
            )
            check("all tools registered despite unreachable Blender", len(listed.tools) == 8, f"{len(listed.tools)} tools")

            started = time.monotonic()
            result = await session.call_tool("blender_status", {})
            elapsed = time.monotonic() - started
            text = "".join(getattr(b, "text", "") for b in result.content)
            check(f"blender_status returned in {elapsed:.2f}s", elapsed < DISCOVERY_BUDGET_S)
            check("status reports not connected", '"connected": false' in text.replace("'", '"'))
            check("status explains what to do", "hint" in text)

            started = time.monotonic()
            err = await session.call_tool("blender_get_scene_info", {})
            elapsed = time.monotonic() - started
            is_error = bool(getattr(err, "is_error", None) or getattr(err, "isError", False))
            message = "".join(getattr(b, "text", "") for b in err.content)
            check(f"a real command failed fast ({elapsed:.2f}s)", elapsed < DISCOVERY_BUDGET_S)
            check("and it surfaced as a tool error", is_error)
            check("with an actionable message", "not reachable" in message, message.strip().splitlines()[0][:120])

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("PASSED - unreachable Blender degrades cleanly and never blocks discovery")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.0.2.10")
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
