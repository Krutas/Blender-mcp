# blender-mcp

Drive a running Blender session from any MCP-capable agent (Hermes, Claude Code,
Cursor, …). Two pieces:

- **`blender_mcp/addon.py`** — a Blender add-on that opens a JSON-over-TCP socket
  inside Blender and executes commands on Blender's main thread.
- **`blender_mcp/server.py`** — an MCP server (stdio) that exposes that socket as
  tools: scene inspection, object inspection, arbitrary `bpy` execution, renders,
  and saving.

The add-on needs nothing but Blender's bundled Python. The MCP side needs the
`mcp` SDK.

## Why this exists (and where the usual one hurts)

The common failure of Blender MCP servers is not Blender — it is the *client*.
`mcp-for-blender` (and friends) open their Blender socket at **startup with no
timeout**. MCP clients call `initialize` + `tools/list` during discovery, so when
Blender is not running, or the port is firewalled with SYNs *dropped* rather than
refused (common across Tailscale / VPN / cloud security groups), `connect()`
blocks for the OS TCP timeout — minutes. Discovery never completes and **no
blender tools load at all**, even though the server is fine.

This implementation is built so that cannot happen:

- **Lazy connections.** Nothing touches the socket at import or startup.
  `initialize` and `tools/list` return instantly, always.
- **Every connect is bounded** (`BLENDER_MCP_CONNECT_TIMEOUT`, default 4s).
- **Failures are legible.** A down Blender yields
  `"Blender add-on not reachable at 127.0.0.1:9876 (…). In Blender: 3D Viewport > Sidebar (N) > Blender MCP > Start Server."`
  — not a hang and not a stack trace.

`blender_status` is the cheap health probe; it never raises.

## Install

```bash
uv venv .venv
uv pip install -e .          # or: pip install -e .
uv pip install pytest        # for the tests

.venv/bin/blender-mcp install     # copy the add-on into Blender
```

Then in Blender: **Edit > Preferences > Add-ons > search "Blender MCP" > tick it**.
The server starts automatically (toggle "Start server when add-on loads"), and the
panel in the N-sidebar has Start/Stop plus the port.

Check every link in the chain:

```bash
.venv/bin/blender-mcp doctor
```

## Headless Blender

```bash
.venv/bin/blender-mcp headless --port 9877            # empty scene
.venv/bin/blender-mcp headless --blend scene.blend    # open a file
.venv/bin/blender-mcp headless --foreground           # stay attached
```

This launches `blender --background --python <launcher>` and detaches. Logs go to
`~/.hermes/cache/blender-mcp-headless.log`.

`blender --background` never pumps `bpy.app.timers`, and it exits the moment the
`--python` script returns. So the generated launcher supplies its own main loop:
it calls `addon.pump_once()` — which runs queued commands on that thread — and
never returns. That is what keeps the process alive *and* keeps `bpy` calls on
Blender's real main thread. Commands that wait `TIMER_GRACE` seconds with no timer
firing fall back to inline execution on the socket thread instead of failing;
`run_once` is idempotent, so the callable still runs exactly once.

## Register with Hermes

```bash
.venv/bin/blender-mcp connect            # runs `hermes mcp add` for you
.venv/bin/blender-mcp connect --print-only   # just show the command
.venv/bin/blender-mcp config            # print the config.yaml snippet
```

`connect` runs the equivalent of:
```bash
hermes mcp add blender_local \
  --command /path/to/.venv/bin/python \
  --env BLENDER_MCP_HOST=127.0.0.1 BLENDER_MCP_PORT=9877 \
  --args -m blender_mcp serve
```

Adding a server requires restarting the agent before its tools appear (they load
as `mcp_blender_local_*`).

## Point it at a remote Blender

The add-on binds loopback by default, so **on the Blender machine you must change
its bind address** or nothing from another host can reach it:

- Headless: `blender-mcp headless --host <tailnet-ip> --port 9876`
- GUI: Add-on Preferences > Blender MCP > Host, then Start Server.

Set it to the machine's tailnet/VPN IP rather than `0.0.0.0`. **This socket runs
arbitrary Python as the user Blender runs as** — anything that can reach it can
execute code on that machine. Binding it to every interface on a host with a
public address hands out remote code execution. Prefer the tailnet IP, and lean
on your ACLs.

Then point the client at that machine — no relay, no port-forwarder:

```yaml
mcp_servers:
  blender:
    command: "/path/to/.venv/bin/python"
    args: ["-m", "blender_mcp", "serve"]
    env:
      BLENDER_MCP_HOST: "192.0.2.10"   # the Blender machine
      BLENDER_MCP_PORT: "9876"
      BLENDER_MCP_CONNECT_TIMEOUT: "4"
    timeout: 180
```

An unreachable remote now costs 4 seconds and a clear message, instead of
breaking tool discovery for the whole agent. (The relay workaround that other
setups need exists only to paper over an unbounded `connect()`.)

Verified: an add-on bound to a tailnet IP is reachable and fully functional from
another host through the same client path — `execute_code` runs real `bpy` over
the network, not just loopback.

Install the add-on on the Blender machine with `blender-mcp install` there, or
copy `blender_mcp/addon.py` to
`~/.config/blender/<version>/scripts/addons/blender_mcp_addon.py`
(`~/Library/Application Support/Blender/...` on macOS,
`%APPDATA%\Blender Foundation\Blender\...` on Windows).

## Tools

| Tool | What it does |
|---|---|
| `blender_status` | Reachability + versions. Never raises; call it first. |
| `blender_get_scene_info` | Engine, frame range, resolution, collections, counts, objects, cameras, lights, materials. |
| `blender_list_objects` | Filter by `kind` (`MESH`, `LIGHT`, …) and/or `name_filter`. |
| `blender_get_object_info` | Transform, dimensions, bounds, mesh stats (verts/edges/tris/UVs), materials, modifiers, constraints, parenting, custom props. |
| `blender_execute_code` | Run arbitrary `bpy` Python. Single expressions are evaluated and their value returned as JSON; otherwise set `result`. |
| `blender_screenshot` | Render and return a PNG image, plus a text block with the strategy and lit-pixel fraction. |
| `blender_save_file` | Save in place, or Save-As with `filepath`. |
| `blender_get_versions` | Blender, packaged Python, add-on and protocol versions. |

`blender_execute_code` is the general-purpose escape hatch — creating geometry,
materials, modifiers, animation, import/export. Its `result` is returned as
native JSON when the value survives a round trip, and as a `repr` otherwise, so a
dict comes back as a dict.

## Rendering notes

`blender_screenshot` picks a strategy per mode and **verifies the output**:

- **Headless (`--background`)** tries a full render first. An OpenGL render needs
  a GL context and simply fails there — `Cannot use OpenGL render in background
  mode (no opengl context)` — so it is not worth trying first.
- **GUI** tries the fast OpenGL viewport render first.

Every frame is measured for the fraction of non-black pixels. If a strategy
returns an empty frame the other one is tried; if both are empty, the frame with
the most lit pixels comes back **with a warning** rather than as an error, because
a scene can legitimately be dark. The lit fraction and winning strategy are always
reported, so the agent can judge for itself. Render settings (resolution, format,
engine samples, `film_transparent`) are restored afterwards.

Two things that produce a black frame and are the caller's problem, not the
server's:

- `bpy.ops.wm.read_factory_settings(use_empty=True)` leaves the scene **with no
  world**, so everything renders against pure black.
- A sun light at its default rotation points straight down; from most camera
  angles the cube's faces are then unlit. Angle the light.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `BLENDER_MCP_HOST` | `127.0.0.1` | Add-on host |
| `BLENDER_MCP_PORT` | `9876` | Add-on port |
| `BLENDER_MCP_TIMEOUT` | `120` | Per-command timeout (s) |
| `BLENDER_MCP_CONNECT_TIMEOUT` | `4` | TCP connect timeout (s) |

## Error reporting

Tool failures come back as **MCP tool errors carrying the real reason**, not as
raised exceptions. Raising from a tool makes the SDK tell the client only
`"Error executing tool blender_get_object_info"` and log the detail to stderr,
where the agent never sees it — useless. So failures return
`CallToolResult(is_error=True, content=[TextContent(...)])`, giving the agent
`ValueError: no object named 'DoesNotExist' in this file` followed by the
Blender-side traceback. Keep this behaviour when adding tools: use `_guarded`,
never raise.

## Protocol

Newline-delimited UTF-8 JSON over TCP, one request per response.

```json
{"type":"command","command":"execute_code","params":{"code":"1+1"},"request_id":"…","protocol":1}
{"type":"response","status":"success","request_id":"…","result":{"ok":true,"result":2,"stdout":"","duration_ms":0.1}}
```

Errors carry a short `error` (`"ValueError: no object named 'X' in this file"`)
plus the full `traceback`, so agents read one line and humans still get detail.
It is plain enough to drive by hand: `nc 127.0.0.1 9876`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q          # protocol + client, no Blender needed
.venv/bin/python scripts/e2e_smoke.py         # full chain, needs a live Blender
bash scripts/restart_headless.sh 9877         # restart headless Blender with the current add-on
```

`tests/test_protocol_and_client.py` drives real sockets against a fake add-on, so
framing, timeouts, error shapes and the base64 screenshot path are exercised for
real — including a regression guard that a dead port fails fast instead of
blocking. `scripts/e2e_smoke.py` spawns the actual MCP server over stdio (exactly
as Hermes does), builds a scene with `execute_code`, inspects it, renders it,
verifies the PNG, and saves a `.blend`.

## Layout

```
blender_mcp/addon.py     Blender add-on: socket server + command handlers
blender_mcp/protocol.py  Framing; shared wire contract
blender_mcp/client.py    Lazy, bounded, blocking client
blender_mcp/server.py    MCP server and tool definitions
blender_mcp/cli.py       install / headless / connect / config / doctor
scripts/                 e2e smoke test, render diagnostics, restart helper
tests/                   Protocol and client tests
```
