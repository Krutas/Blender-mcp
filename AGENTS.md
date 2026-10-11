# AGENTS.md

`blender-mcp` exposes a running Blender session to MCP-capable agents. Two halves:
`blender_mcp/addon.py` is a Blender add-on that runs a JSON-over-TCP socket inside
Blender; `blender_mcp/server.py` is an MCP server (stdio) that speaks that socket.
The MCP side needs the `mcp` SDK; the add-on needs only Blender's bundled Python.

## Dev environment

```bash
uv venv .venv
uv pip install -e .
uv pip install pytest          # or: uv pip install -e ".[dev]"
```

Python >= 3.10. Not a git repo — no commit/push workflow here. There is no
Makefile, CI config, or linter; pytest (configured in `pyproject.toml`,
`testpaths = ["tests"]`, `addopts = "-q"`) is the only quality gate.

## Build & test

```bash
.venv/bin/python -m pytest tests/ -q          # 45 tests; no Blender needed
.venv/bin/python scripts/e2e_smoke.py --port 9877   # full chain; needs live Blender
bash scripts/restart_headless.sh 9877         # restart headless Blender on the current add-on
.venv/bin/blender-mcp doctor                  # check Blender, add-on, socket, SDK, Hermes config
```

`tests/` uses fake `bpy` (installed in `sys.modules`) and fake socket servers, so it
runs anywhere. `scripts/*.py` (all run with the venv python, not bare `python`) drive
a live Blender: `diagnose_render.py`, `shot_startup_scene.py`, `direct_shot.py`,
`verify_unreachable_host.py`. `restart_headless.sh` hardcodes `REPO=/root/blender-mcp`
and defaults to port 9877.

## Conventions

- Every module starts with `from __future__ import annotations` and a real docstring
  explaining the *why* (threading model, failure modes), not a restatement of the code.
- Errors are values, not exceptions, at the MCP boundary: tools return
  `CallToolResult(is_error=True, ...)` via `server._guarded` / `_error_result`, never
  `raise`. Raising makes the SDK hide the real reason from the client.
- `BlenderClient` failures use two exception types: `BlenderNotRunning` (socket unreachable)
  and `BlenderError` (add-on answered `status: error`, carries `.traceback`).
- Tests are `test_<behavior>` functions with a docstring on the non-obvious ones
  (e.g. the bounded-connect regression guard). No classes except fakes/helpers.

## Pitfalls

- **Never connect during MCP startup or import.** Lazy, bounded connections are the
  whole point of this repo (`BLENDER_MCP_CONNECT_TIMEOUT`, default 4s). An eager
  `socket.connect()` to a firewalled (SYN-dropped) port blocks `initialize` + `tools/list`
  for minutes and no blender tools load at all. Don't reintroduce it.
- **`addon.py` must import only the stdlib + `bpy`.** Blender's bundled Python has no pip.
  No third-party imports there, ever.
- **`bpy` is not thread-safe.** Socket handlers never call `bpy` directly; commands go
  through the `_Call` queue drained by `pump_once()` on Blender's main thread.
- **Generated, don't hand-edit:** `blender-mcp headless` writes a launcher to
  `~/.hermes/cache/blender-mcp-headless.py` (override with `--launcher`) and copies
  `addon.py` into Blender's addons dir; `blender-mcp install` copies `addon.py` as
  `blender_mcp_addon.py`. Edit the source in `blender_mcp/addon.py`.
- **After changing `addon.py`, reinstall it** (`restart_headless.sh` does this) or the
  running Blender keeps the old copy.
- **Ports:** default is `9876`; this host uses `9877`. A legacy `127.0.0.1:9876` listener
  exists — pick another port if `bind` fails.
- **Black renders are usually the caller's scene**, not the server: `read_factory_settings(use_empty=True)`
  leaves no world, and a default-rotation sun lights nothing from most angles. See
  `scripts/diagnose_render.py` and the README's "Rendering notes".
- **`blender_screenshot` is slow on CPU-only headless builds** — take one at the end of a task.
