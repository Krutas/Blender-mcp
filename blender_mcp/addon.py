"""Blender add-on: a JSON-over-TCP control socket for AI agents.

Install this file into Blender's add-on directory (``blender-mcp install``), then
enable "Blender MCP" in Preferences > Add-ons. The add-on exposes a small
localhost socket; ``blender_mcp.server`` speaks to it.

Self-contained by design: Blender's bundled Python has no ``pip`` guarantees, so
this file imports nothing outside the standard library plus ``bpy``.

Threading model
---------------
``bpy`` is not thread-safe: almost every operator must run on Blender's main
thread, otherwise you get silent corruption or a hard crash. The socket server
therefore never touches ``bpy`` directly. Each command is wrapped in a
``_Call``, pushed onto a queue, and drained by a persistent
``bpy.app.timers`` callback on the main thread. The socket handler blocks on the
call's ``Event`` for the result.

Headless caveat: ``blender --background`` never pumps ``bpy.app.timers``, and it
exits as soon as the ``--python`` script returns. The ``blender-mcp headless``
launcher therefore supplies its own main loop, calling :func:`pump_once` -- which
runs queued commands on that thread -- and stays alive by never returning. When a
command waits ``TIMER_GRACE`` seconds without any timer firing, the handler
concludes nothing is pumping the event loop and runs the callable inline on the
socket thread instead of failing. A lock guarantees the callable runs exactly once
whichever path wins.
"""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import socket
import socketserver
import threading
import time
import traceback

import bpy

bl_info = {
    "name": "Blender MCP",
    "author": "Hermes Agent",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D Viewport > Sidebar (N) > Blender MCP",
    "description": "Exposes a local JSON socket so AI agents can inspect and drive Blender.",
    "category": "Development",
}

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
MAX_MESSAGE_BYTES = 32 * 1024 * 1024
DRAIN_INTERVAL = 0.05


# --------------------------------------------------------------------------
# main-thread dispatch
# --------------------------------------------------------------------------


class _Call:
    __slots__ = ("fn", "event", "result", "error", "claim", "done")

    def __init__(self, fn):
        self.fn = fn
        self.event = threading.Event()
        self.result = None
        self.error = None
        self.claim = threading.Lock()
        self.done = False

    def run_once(self):
        """Execute the callable exactly once, no matter which thread wins.

        The latch matters: a call can be raced by the main-thread timer and by
        the socket thread's inline fallback. Without it the loser would re-run
        the command -- harmless for a scene query, destructive for
        ``execute_code`` that creates objects or writes files.
        """
        with self.claim:
            if self.done:
                return
            self.done = True
            try:
                self.result = self.fn()
            except BaseException as exc:  # noqa: BLE001 - reported back over the wire
                self.error = exc
            finally:
                self.event.set()


_pending: "queue.Queue[_Call]" = queue.Queue()
_dispatch_lock = threading.Lock()
_dispatched_calls = 0
_inline_fallbacks = 0
_timer_registered = False

#: How long a command waits for the main-thread timer before concluding that
#: nothing is pumping Blender's event loop and executing inline instead. The
#: timer fires every DRAIN_INTERVAL, so a live loop always beats this by ~40x.
TIMER_GRACE = 2.0

#: Monotonic timestamp of the last main-thread drain, used as a liveness probe.
_last_drain = 0.0


def pump_once() -> int:
    """Run every queued call on the calling thread; return how many ran.

    Public so a custom main loop -- the headless launcher, which cannot rely on
    ``bpy.app.timers`` because ``blender --background`` never pumps them -- can
    drive dispatch itself from Blender's real main thread.
    """
    ran = 0
    while True:
        try:
            call = _pending.get_nowait()
        except queue.Empty:
            break
        call.run_once()
        ran += 1
    return ran


def _drain():
    global _last_drain
    _last_drain = time.monotonic()
    pump_once()
    return DRAIN_INTERVAL


def _ensure_drain_registered() -> bool:
    global _timer_registered, _last_drain
    if _timer_registered:
        return True
    try:
        bpy.app.timers.register(_drain, persistent=True)
    except Exception:  # pragma: no cover - only on exotic builds
        return False
    _timer_registered = True
    # Start the liveness clock now so the first command gives the timer a fair
    # chance instead of racing straight to the inline path.
    _last_drain = time.monotonic()
    return True


def run_on_main_thread(fn, timeout: float = 30.0):
    """Run ``fn`` on Blender's main thread and return its result."""
    global _dispatched_calls, _inline_fallbacks

    call = _Call(fn)

    if not _timer_registered:
        _ensure_drain_registered()
    _pending.put(call)
    _dispatched_calls += 1

    deadline = time.monotonic() + timeout
    while True:
        if call.event.wait(0.05):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"command did not complete within {timeout}s")
        # No timer has fired for a while -> no event loop is pumping (headless
        # or a custom main loop). run_once() is idempotent, so executing here
        # is safe even if the timer claims the call a moment later.
        if not _timer_registered or (time.monotonic() - _last_drain) > TIMER_GRACE:
            _inline_fallbacks += 1
            call.run_once()
            if not call.event.wait(timeout):
                raise TimeoutError(f"command did not complete within {timeout}s")
            break

    if call.error is not None:
        raise call.error
    return call.result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _vec(value, ndigits=4):
    return [round(float(component), ndigits) for component in value]


def _object_counts():
    counts = {}
    for obj in bpy.data.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
    return counts


def _resolve_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"no object named {name!r} in this file")
    return obj


# --------------------------------------------------------------------------
# command handlers (all run on the main thread)
# --------------------------------------------------------------------------


def cmd_ping(params):
    return {
        "pong": True,
        "addon_version": ".".join(str(v) for v in bl_info["version"]),
        "blender_version": bpy.app.version_string,
        "protocol": PROTOCOL_VERSION,
        "background": bool(bpy.app.background),
        "filepath": bpy.data.filepath,
    }


def cmd_get_scene_info(params):
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    objects = list(bpy.data.objects)
    limit = int(params.get("object_limit", 100))
    active = view_layer.objects.active

    return {
        "scene": scene.name,
        "filepath": bpy.data.filepath,
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "render_engine": scene.render.engine,
        "resolution": {
            "width": scene.render.resolution_x,
            "height": scene.render.resolution_y,
            "percentage": scene.render.resolution_percentage,
        },
        "unit_system": scene.unit_settings.system,
        "active_object": active.name if active else None,
        "selected_objects": [o.name for o in view_layer.objects if o.select_get()][:limit],
        "collections": [c.name for c in bpy.data.collections],
        "object_counts": _object_counts(),
        "objects": [
            {"name": o.name, "type": o.type, "location": _vec(o.location)} for o in objects[:limit]
        ],
        "objects_truncated": max(0, len(objects) - limit),
        "materials": [m.name for m in bpy.data.materials][:limit],
        "cameras": [o.name for o in objects if o.type == "CAMERA"],
        "lights": [o.name for o in objects if o.type == "LIGHT"],
        "world": scene.world.name if scene.world else None,
    }


def cmd_list_objects(params):
    kind = params.get("kind")
    name_filter = (params.get("name_filter") or "").lower()
    limit = int(params.get("limit", 200))

    matches = []
    for obj in bpy.data.objects:
        if kind and obj.type != kind.upper():
            continue
        if name_filter and name_filter not in obj.name.lower():
            continue
        matches.append(
            {
                "name": obj.name,
                "type": obj.type,
                "location": _vec(obj.location),
                "dimensions": _vec(obj.dimensions),
                "parent": obj.parent.name if obj.parent else None,
                "visible": not obj.hide_viewport,
            }
        )
    total = len(matches)
    return {"count": total, "returned": min(total, limit), "objects": matches[:limit]}


def cmd_get_object_info(params):
    obj = _resolve_object(params["name"])
    info = {
        "name": obj.name,
        "type": obj.type,
        "location": _vec(obj.location),
        "rotation_euler_deg": [round(float(a) * 57.29577951308232, 3) for a in obj.rotation_euler],
        "rotation_mode": obj.rotation_mode,
        "scale": _vec(obj.scale),
        "dimensions": _vec(obj.dimensions),
        "bound_box": [_vec(corner) for corner in obj.bound_box],
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "modifiers": [
            {"name": m.name, "type": m.type, "show_viewport": m.show_viewport}
            for m in obj.modifiers
        ],
        "constraints": [{"name": c.name, "type": c.type} for c in obj.constraints],
        "materials": [s.material.name if s.material else None for s in obj.material_slots],
        "visible": not obj.hide_viewport,
        "custom_properties": {
            k: repr(v.value) for k, v in obj.items() if k != "_RNA_UI"
        },
    }

    data = getattr(obj, "data", None)
    if obj.type == "MESH" and data is not None:
        stats = {
            "vertices": len(data.vertices),
            "edges": len(data.edges),
            "polygons": len(data.polygons),
        }
        try:
            data.calc_loop_triangles()
            stats["triangles"] = len(data.loop_triangles)
        except Exception:
            pass
        stats["uv_layers"] = [layer.name for layer in data.uv_layers]
        stats["color_attributes"] = [a.name for a in data.color_attributes]
        info["mesh"] = stats
        info["vertex_groups"] = [g.name for g in obj.vertex_groups]
    elif obj.type == "CAMERA" and data is not None:
        info["camera"] = {
            "lens_mm": round(float(data.lens), 3),
            "sensor_width_mm": round(float(data.sensor_width), 3),
            "clip_start": round(float(data.clip_start), 4),
            "clip_end": round(float(data.clip_end), 4),
            "type": data.type,
        }
    elif obj.type == "LIGHT" and data is not None:
        info["light"] = {
            "type": data.type,
            "energy": round(float(data.energy), 4),
            "color": _vec(data.color),
        }
    elif obj.type == "TEXT" and data is not None:
        info["text"] = {"body": data.body[:2000]}

    return info


def _jsonable(value):
    """Return ``value`` if JSON can encode it, else its repr.

    Agents consume tool output as JSON; a Python repr of a plain dict/list is
    noise they have to un-learn. Keep native structure whenever it survives a
    round trip and only fall back to repr for bpy objects and the like.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError, RecursionError):
        return repr(value)


def cmd_execute_code(params):
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("'code' must be a non-empty string")

    namespace = {"bpy": bpy, "__name__": "__main__", "__builtins__": __builtins__}
    buffer = io.StringIO()
    started = time.time()

    import contextlib

    result_value = None
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                # A single expression is by far the most common case; evaluate
                # it so the caller gets the value rather than None.
                result_value = eval(compile(code, "<blender-mcp>", "eval"), namespace)  # noqa: S307
            except SyntaxError:
                exec(compile(code, "<blender-mcp>", "exec"), namespace)  # noqa: S102
                result_value = namespace.get("result")
    except BaseException as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "stdout": buffer.getvalue(),
            "duration_ms": round((time.time() - started) * 1000, 2),
        }

    return {
        "ok": True,
        "result": _jsonable(result_value),
        "stdout": buffer.getvalue(),
        "duration_ms": round((time.time() - started) * 1000, 2),
    }


def _render_opengl(scene, path):
    bpy.ops.render.opengl(write_still=True, view_context=False)


def _render_full(scene, path):
    bpy.ops.render.render(write_still=True)


def _image_content_ratio(image):
    """Fraction of pixels that are not near-black, plus mean luma.

    Used to detect a render that "succeeded" but produced an empty frame --
    which is exactly what an OpenGL render does on a headless build with no GL
    context: it writes a black PNG without raising.
    """
    import array

    # image.pixels is already flat RGBA, so the float count IS len(pixels);
    # 4 bytes per float. Over-allocating makes foreach_get raise a length error.
    count = len(image.pixels)
    buffer = array.array("f", bytes(4 * count))
    image.pixels.foreach_get(buffer)
    pixels = count // 4
    if pixels == 0:
        return 0.0, 0.0
    nonblack = 0
    total = 0.0
    for i in range(0, len(buffer), 4):
        value = buffer[i] + buffer[i + 1] + buffer[i + 2]
        total += value
        if value > 0.03:
            nonblack += 1
    return nonblack / pixels, total / pixels / 3.0


#: Below this fraction of lit pixels a frame is treated as an empty render.
#: Kept deliberately tiny: it exists to catch a strategy that produced nothing
#: at all, not to second-guess a legitimately dark scene, which has real content
#: but few lit pixels. The lit fraction is always reported so the caller can
#: judge darkness for itself.
MIN_CONTENT_RATIO = 0.0001


def cmd_screenshot(params):
    """Render a PNG of the scene.

    Two strategies exist and neither is universally correct. An OpenGL viewport
    render is near-instant but needs a GL context, so on a headless build it
    typically writes a black frame without complaining. A full render always
    works but costs real time, and cannot run without a scene camera.

    So: try the strategy that suits the mode first, verify the result actually
    has content, and fall through to the other one otherwise. If every strategy
    comes back blank, return the frame with the most lit pixels alongside a
    warning rather than failing -- the scene may legitimately be dark.
    """
    max_size = int(params.get("max_size", 1024))
    max_size = max(64, min(max_size, 4096))
    scene = bpy.context.scene
    import tempfile

    strategies = (
        [("render", _render_full), ("opengl", _render_opengl)]
        if bpy.app.background
        else [("opengl", _render_opengl), ("render", _render_full)]
    )

    attempts = []
    best = None

    with _temporary_render_settings(scene, max_size):
        for name, run in strategies:
            path = os.path.join(
                tempfile.gettempdir(), f"blender_mcp_{os.getpid()}_{int(time.time() * 1000)}.png"
            )
            scene.render.filepath = path
            try:
                run(scene, path)
            except Exception as exc:
                attempts.append(f"{name}: {exc}")
                continue
            if not os.path.exists(path):
                attempts.append(f"{name}: produced no file")
                continue

            image = bpy.data.images.load(path, check_existing=False)
            try:
                ratio, luma = _image_content_ratio(image)
                width, height = image.size
                if ratio < MIN_CONTENT_RATIO:
                    attempts.append(f"{name}: blank frame (lit {ratio:.4%}, luma {luma:.4f})")
                    if best is None or ratio > best["ratio"]:
                        best = {"ratio": ratio, "image": path, "strategy": name}
                    else:
                        _remove_quietly(path)
                    continue
                payload = _png_bytes(image)
            finally:
                bpy.data.images.remove(image)
            _remove_quietly(path)
            return {
                "format": "png",
                "width": int(width),
                "height": int(height),
                "bytes": len(payload),
                "strategy": name,
                "lit_fraction": round(ratio, 5),
                "data": base64.b64encode(payload).decode("ascii"),
            }

    if best is not None:
        image = bpy.data.images.load(best["image"], check_existing=False)
        try:
            width, height = image.size
            payload = _png_bytes(image)
        finally:
            bpy.data.images.remove(image)
        _remove_quietly(best["image"])
        return {
            "format": "png",
            "width": int(width),
            "height": int(height),
            "bytes": len(payload),
            "strategy": best["strategy"],
            "lit_fraction": round(best["ratio"], 5),
            "warning": (
                "every render strategy produced an empty frame (no lit pixels). "
                "Attempts: " + "; ".join(attempts)
            ),
            "data": base64.b64encode(payload).decode("ascii"),
        }

    hint = ""
    if scene.camera is None:
        hint = " The scene has no active camera; set bpy.context.scene.camera first."
    raise RuntimeError("screenshot failed; " + "; ".join(attempts) + hint)


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _png_bytes(image):
    import tempfile

    path = os.path.join(tempfile.gettempdir(), f"blender_mcp_enc_{os.getpid()}_{int(time.time()*1000)}.png")
    original_format = image.file_format
    try:
        image.file_format = "PNG"
        image.save_render(path)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        image.file_format = original_format
        try:
            os.remove(path)
        except OSError:
            pass


class _temporary_render_settings:
    """Context manager that restores every render setting it touches."""

    def __init__(self, scene, max_size):
        self.scene = scene
        self.max_size = max_size

    def __enter__(self):
        render = self.scene.render
        image_settings = render.image_settings
        self.saved = {
            "filepath": render.filepath,
            "format": image_settings.file_format,
            "engine": render.engine,
            "res_x": render.resolution_x,
            "res_y": render.resolution_y,
            "pct": render.resolution_percentage,
            "samples": getattr(self.scene.cycles, "samples", None) if hasattr(self.scene, "cycles") else None,
        }
        render.film_transparent = False
        render.image_settings.file_format = "PNG"
        ratio = render.resolution_y / max(1, render.resolution_x)
        render.resolution_x = self.max_size
        render.resolution_y = max(1, int(self.max_size * ratio))
        render.resolution_percentage = 100
        if self.saved["samples"] is not None:
            self.saved_engine_samples = self.scene.cycles.samples
            self.scene.cycles.samples = min(self.scene.cycles.samples, 16)
        return self

    def __exit__(self, *exc_info):
        render = self.scene.render
        render.filepath = self.saved["filepath"]
        render.image_settings.file_format = self.saved["format"]
        render.resolution_x = self.saved["res_x"]
        render.resolution_y = self.saved["res_y"]
        render.resolution_percentage = self.saved["pct"]
        if self.saved["samples"] is not None:
            self.scene.cycles.samples = self.saved_engine_samples
        return False


def cmd_save_file(params):
    filepath = params.get("filepath")
    if filepath:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.expanduser(filepath))
    else:
        bpy.ops.wm.save_mainfile()
    return {"saved": True, "filepath": bpy.data.filepath}


def cmd_get_versions(params):
    return {
        "blender": bpy.app.version_string,
        "blender_version": list(bpy.app.version),
        "python": bpy.app.version_string and __import__("sys").version.split()[0],
        "addon": ".".join(str(v) for v in bl_info["version"]),
        "protocol": PROTOCOL_VERSION,
        "background": bool(bpy.app.background),
    }


COMMANDS = {
    "ping": cmd_ping,
    "get_versions": cmd_get_versions,
    "get_scene_info": cmd_get_scene_info,
    "list_objects": cmd_list_objects,
    "get_object_info": cmd_get_object_info,
    "execute_code": cmd_execute_code,
    "screenshot": cmd_screenshot,
    "save_file": cmd_save_file,
}

#: Commands allowed to run inline on the socket thread when no timer fires.
#: Kept identical to COMMANDS today; the split exists so a future command that
#: is unsafe off the main thread can be marked here.
MAIN_THREAD_ONLY = set()


# --------------------------------------------------------------------------
# socket server
# --------------------------------------------------------------------------


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(self.server.command_timeout)
        buffer = bytearray()
        try:
            while True:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                buffer.extend(chunk)
                if len(buffer) > MAX_MESSAGE_BYTES:
                    self._send_error(None, "message exceeds size limit")
                    return
                while True:
                    index = buffer.find(b"\n")
                    if index == -1:
                        break
                    raw = bytes(buffer[:index])
                    del buffer[: index + 1]
                    if raw.strip():
                        self._process(raw)
        except (socket.timeout, ConnectionResetError, OSError):
            return

    def _send_error(self, request_id, message, result=None):
        payload = {"type": "response", "status": "error", "request_id": request_id, "error": message}
        if result is not None:
            payload["result"] = result
        try:
            self.request.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        except OSError:
            pass

    def _process(self, raw):
        request_id = None
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            request_id = request.get("request_id")
            command = request.get("command")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("'params' must be an object")

            handler = COMMANDS.get(command)
            if handler is None:
                raise ValueError(
                    f"unknown command {command!r}; known: {', '.join(sorted(COMMANDS))}"
                )

            timeout = float(params.pop("_timeout", self.server.command_timeout))

            def invoke():
                return handler(params)

            if bpy.app.background and command in MAIN_THREAD_ONLY:
                result = invoke()
            else:
                result = run_on_main_thread(invoke, timeout=timeout)

            response = {
                "type": "response",
                "status": "success",
                "request_id": request_id,
                "result": result,
            }
        except Exception as exc:
            response = {
                "type": "response",
                "status": "error",
                "request_id": request_id,
                # Concise first line for the agent, full detail in "traceback".
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        try:
            self.request.sendall(json.dumps(response).encode("utf-8") + b"\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    command_timeout = 60.0


_server = None
_server_thread = None
_server_lock = threading.Lock()


def server_is_running():
    return _server is not None


def start_server(host=DEFAULT_HOST, port=DEFAULT_PORT, command_timeout=60.0):
    global _server, _server_thread, _timer_registered

    with _server_lock:
        if _server is not None:
            return False
        _timer_registered = _ensure_drain_registered()
        _server = _Server((host, port), _Handler)
        _server.command_timeout = command_timeout
        _server_thread = threading.Thread(target=_server.serve_forever, name="blender-mcp", daemon=True)
        _server_thread.start()
    return True


def stop_server():
    global _server, _server_thread

    with _server_lock:
        if _server is None:
            return False
        _server.shutdown()
        _server.server_close()
        _server = None
        _server_thread = None
    return True


# --------------------------------------------------------------------------
# preferences, operators, UI
# --------------------------------------------------------------------------


class BlenderMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    host: bpy.props.StringProperty(name="Host", default=DEFAULT_HOST)
    port: bpy.props.IntProperty(name="Port", default=DEFAULT_PORT, min=1024, max=65535)
    auto_start: bpy.props.BoolProperty(name="Start server when add-on loads", default=True)
    command_timeout: bpy.props.FloatProperty(name="Command timeout (s)", default=60.0, min=1.0, max=600.0)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "auto_start")
        layout.prop(self, "command_timeout")


class BLENDERMCP_OT_start(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Start Blender MCP Server"
    bl_description = "Open the local control socket for AI agents"

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        try:
            started = start_server(prefs.host, prefs.port, prefs.command_timeout)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not bind {prefs.host}:{prefs.port} - {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Blender MCP server started" if started else "Already running")
        return {"FINISHED"}


class BLENDERMCP_OT_stop(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop Blender MCP Server"

    def execute(self, context):
        self.report({"INFO"}, "Stopped" if stop_server() else "Was not running")
        return {"FINISHED"}


class BLENDERMCP_PT_panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blender MCP"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        running = server_is_running()
        box = layout.box()
        box.label(text="Server running" if running else "Server stopped", icon="PLAY" if running else "PAUSE")
        box.label(text=f"{prefs.host}:{prefs.port}")
        row = layout.row()
        row.enabled = not running
        row.operator("blendermcp.start_server", icon="PLAY")
        row = layout.row()
        row.enabled = running
        row.operator("blendermcp.stop_server", icon="PAUSE")
        layout.prop(prefs, "port")


_CLASSES = (
    BlenderMCPPreferences,
    BLENDERMCP_OT_start,
    BLENDERMCP_OT_stop,
    BLENDERMCP_PT_panel,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    prefs = bpy.context.preferences.addons[__name__].preferences
    if prefs.auto_start:
        try:
            start_server(prefs.host, prefs.port, prefs.command_timeout)
        except OSError as exc:
            print(f"[blender-mcp] could not auto-start server: {exc}")


def unregister():
    stop_server()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
