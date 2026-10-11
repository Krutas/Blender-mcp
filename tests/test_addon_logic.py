"""Tests for the Blender add-on's dispatch and command logic.

The add-on is normally inseparable from Blender, but everything interesting --
the main-thread queue, the inline fallback, the error shape, the blank-frame
detector -- is plain Python. A fake ``bpy`` module is installed in ``sys.modules``
before the add-on is imported so it can be exercised directly, and real sockets
are used against a real server instance.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import types
from typing import Any

import pytest


# --------------------------------------------------------------------------
# fake bpy, installed before the add-on is imported
# --------------------------------------------------------------------------


class _FakeTimers:
    def __init__(self):
        self.registered = []
        self.pump: Any = None

    def register(self, fn, persistent=False):
        self.registered.append(fn)
        self.pump = fn
        return None


def _install_fake_bpy():
    bpy = types.ModuleType("bpy")
    app = types.SimpleNamespace(
        version_string="5.0.1",
        version=(5, 0, 1),
        background=True,
        timers=_FakeTimers(),
    )
    data = types.SimpleNamespace(filepath="")

    # The add-on declares its UI classes at module scope, so the bases it
    # inherits from must exist. `from __future__ import annotations` means the
    # bpy.props.* annotations are never evaluated, so bpy.props only needs to
    # be present, not functional.
    class _AddonPreferences:
        pass

    class _Operator:
        pass

    class _Panel:
        pass

    bpy.app = app
    bpy.data = data
    bpy.context = types.SimpleNamespace()
    bpy.types = types.SimpleNamespace(
        AddonPreferences=_AddonPreferences, Operator=_Operator, Panel=_Panel
    )
    bpy.utils = types.SimpleNamespace()
    bpy.props = types.SimpleNamespace()
    sys.modules["bpy"] = bpy
    return bpy


FAKE_BPY = _install_fake_bpy()

from blender_mcp import addon  # noqa: E402  (must follow the fake bpy)
from blender_mcp.client import BlenderClient  # noqa: E402
from blender_mcp.protocol import encode_message, make_request  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_grace(monkeypatch):
    """Reset shared dispatch state between tests.

    ``_last_drain`` and ``_timer_registered`` are module globals that the
    timeout test deliberately pushes into the future; leaving them set would
    make every later test wait forever for a timer that will never fire.
    """
    monkeypatch.setattr(addon, "TIMER_GRACE", 0.2)
    monkeypatch.setattr(addon, "_timer_registered", False)
    monkeypatch.setattr(addon, "_last_drain", 0.0)
    while not addon._pending.empty():
        addon._pending.get_nowait()


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def test_call_run_once_executes_exactly_once():
    """Both the timer and the socket thread may race to run a call."""
    runs = []
    call = addon._Call(lambda: runs.append(1))

    call.run_once()
    call.run_once()
    call.run_once()

    assert runs == [1]
    assert call.event.is_set()
    assert call.error is None


def test_call_captures_exception_and_still_signals():
    call = addon._Call(lambda: 1 / 0)
    call.run_once()
    assert isinstance(call.error, ZeroDivisionError)
    assert call.event.is_set()


def test_call_never_executes_twice_under_concurrent_race():
    """Regression guard: the timer and the inline fallback both call run_once."""
    runs = []
    call = addon._Call(lambda: (time.sleep(0.05), runs.append(1))[1])

    threads = [threading.Thread(target=call.run_once) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert runs == [1]
    assert call.event.is_set()


def test_pump_once_runs_queued_calls_on_the_calling_thread():
    seen = []
    for index in range(3):
        addon._pending.put(addon._Call(lambda i=index: seen.append(i)))
    assert addon.pump_once() == 3
    assert seen == [0, 1, 2]
    assert addon.pump_once() == 0


def test_run_on_main_thread_uses_timer_path_when_pumped():
    """When something drains the queue, the value comes back without fallback."""
    addon._timer_registered = True
    addon._last_drain = time.monotonic()  # the timer looks alive, as in the GUI
    before = addon._inline_fallbacks
    results = []

    def worker():
        results.append(addon.run_on_main_thread(lambda: "from-main", timeout=5))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for _ in range(200):
        addon.pump_once()
        if len(results) == 3:
            break
        time.sleep(0.01)
    for thread in threads:
        thread.join(timeout=5)

    assert results == ["from-main"] * 3
    assert addon._inline_fallbacks == before


def test_run_on_main_thread_falls_back_inline_when_nothing_pumps_timers():
    """Headless: no event loop means the timer never fires, so run it here."""
    addon._timer_registered = True
    addon._last_drain = time.monotonic() - 60  # pretend no timer has fired
    before = addon._inline_fallbacks
    assert addon.run_on_main_thread(lambda: 42, timeout=5) == 42
    assert addon._inline_fallbacks == before + 1


def test_run_on_main_thread_propagates_errors():
    addon._timer_registered = True
    addon._last_drain = time.monotonic() - 60
    with pytest.raises(ValueError, match="nope"):
        addon.run_on_main_thread(_raise_value_error, timeout=5)


def _raise_value_error():
    raise ValueError("nope")


def test_run_on_main_thread_times_out_when_the_call_hangs():
    addon._timer_registered = True
    addon._last_drain = time.monotonic() + 3600  # make the timer look alive
    with pytest.raises(TimeoutError):
        addon.run_on_main_thread(lambda: time.sleep(5), timeout=0.3)


# --------------------------------------------------------------------------
# helpers used by the command handlers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (True, True),
        (3, 3),
        (1.5, 1.5),
        ("s", "s"),
        ({"a": [1, 2]}, {"a": [1, 2]}),
    ],
)
def test_jsonable_preserves_native_structure(value, expected):
    assert addon._jsonable(value) == expected


def test_jsonable_falls_back_to_repr_for_opaque_objects():
    class Opaque:
        def __repr__(self):
            return "<bpy.types.Object at 0x1>"

    assert addon._jsonable(Opaque()) == "<bpy.types.Object at 0x1>"


class _FakePixels:
    def __init__(self, values):
        self._values = values

    def __len__(self):
        return len(self._values)

    def foreach_get(self, buffer):
        for index, value in enumerate(self._values):
            buffer[index] = value


def _image(values):
    return types.SimpleNamespace(pixels=_FakePixels(values), size=(2, 2), file_format="PNG")


def test_image_content_ratio_detects_an_entirely_black_frame():
    black = [0.0] * 16
    ratio, luma = addon._image_content_ratio(_image(black))
    assert ratio == 0.0
    assert luma == 0.0


def test_image_content_ratio_counts_lit_pixels():
    # Two fully white pixels, two black ones: half the frame is lit, and mean
    # luma is (3+3+0+0)/4 pixels / 3 channels = 0.5.
    values = [1.0, 1.0, 1.0, 1.0] * 2 + [0.0] * 8
    ratio, luma = addon._image_content_ratio(_image(values))
    assert ratio == 0.5
    assert luma == pytest.approx(0.5)


def test_black_frame_is_below_the_empty_threshold():
    ratio, _ = addon._image_content_ratio(_image([0.0] * 16))
    assert ratio < addon.MIN_CONTENT_RATIO


# --------------------------------------------------------------------------
# the socket server, end to end
# --------------------------------------------------------------------------


class _ServerFixture:
    def __init__(self):
        addon.start_server("127.0.0.1", 0, command_timeout=10.0)
        self.port = addon._server.server_address[1]

    def close(self):
        addon.stop_server()


@pytest.fixture
def server():
    fixture = _ServerFixture()
    try:
        yield fixture
    finally:
        fixture.close()


def _raw_call(port, payload, timeout=10.0):
    """Send a raw request and return the decoded response."""
    sock = socket.socket()
    sock.settimeout(timeout)
    sock.connect(("127.0.0.1", port))
    try:
        sock.sendall(encode_message(payload))
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buffer.extend(chunk)
        return json.loads(bytes(buffer).split(b"\n")[0])
    finally:
        sock.close()


def test_server_answers_ping_through_the_real_socket(server):
    response = _raw_call(server.port, make_request("ping"))
    assert response["status"] == "success"
    assert response["result"]["pong"] is True
    assert response["result"]["blender_version"] == "5.0.1"
    assert response["result"]["background"] is True


def test_server_accepts_the_project_client(server):
    assert BlenderClient(port=server.port).call("ping")["pong"] is True


def test_unknown_command_returns_a_concise_error_and_a_traceback(server):
    response = _raw_call(server.port, make_request("no_such_command"))
    assert response["status"] == "error"
    assert "unknown command 'no_such_command'" in response["error"]
    assert "known:" in response["error"]
    assert "Traceback" in response["traceback"]


def test_handler_exception_is_reported_without_killing_the_server(server):
    def explode(params):
        raise ValueError("no object named 'X' in this file")

    addon.COMMANDS["_explode"] = explode
    try:
        response = _raw_call(server.port, make_request("_explode"))
        assert response["status"] == "error"
        assert response["error"] == "ValueError: no object named 'X' in this file"
        assert "Traceback" in response["traceback"]
        # The server survives and still serves the next request.
        assert _raw_call(server.port, make_request("ping"))["status"] == "success"
    finally:
        addon.COMMANDS.pop("_explode", None)


def test_non_object_params_are_rejected(server):
    request = make_request("ping")
    request["params"] = ["not", "a", "dict"]
    response = _raw_call(server.port, request)
    assert response["status"] == "error"
    assert "'params' must be an object" in response["error"]


def test_execute_code_reports_a_concise_error(server):
    response = _raw_call(server.port, make_request("execute_code", {"code": "1/0"}))
    assert response["status"] == "success"  # the command ran; the user code failed
    result = response["result"]
    assert result["ok"] is False
    assert result["error"] == "ZeroDivisionError: division by zero"
    assert "Traceback" in result["traceback"]


def test_execute_code_rejects_empty_code(server):
    response = _raw_call(server.port, make_request("execute_code", {"code": "   "}))
    assert response["status"] == "error"
    assert "'code' must be a non-empty string" in response["error"]


def test_server_handles_several_requests_on_one_connection(server):
    sock = socket.socket()
    sock.settimeout(10)
    sock.connect(("127.0.0.1", server.port))
    try:
        sock.sendall(encode_message(make_request("ping")) + encode_message(make_request("get_versions")))
        buffer = bytearray()
        while buffer.count(b"\n") < 2:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buffer.extend(chunk)
        lines = [json.loads(line) for line in bytes(buffer).split(b"\n") if line.strip()]
        assert [entry["status"] for entry in lines] == ["success", "success"]
        assert lines[1]["result"]["blender"] == "5.0.1"
    finally:
        sock.close()


def test_start_and_stop_are_idempotent(server):
    assert addon.server_is_running() is True
    assert addon.start_server("127.0.0.1", server.port) is False  # already running
    assert addon.stop_server() is True
