"""In-process tests for the wire protocol and the MCP client.

These run without Blender: a fake add-on server speaks the same socket protocol
so the client and framing logic are exercised for real (real sockets, real
JSON, real timeouts).
"""

from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager

import pytest

from blender_mcp.client import BlenderClient, BlenderError, BlenderNotRunning
from blender_mcp.protocol import (
    MessageStream,
    ProtocolError,
    encode_message,
    make_request,
    make_response,
)


# --------------------------------------------------------------------------
# protocol
# --------------------------------------------------------------------------


def test_encode_message_is_one_newline_terminated_frame():
    frame = encode_message({"a": "has\nnewline", "b": [1, 2]})
    assert frame.endswith(b"\n")
    assert frame.count(b"\n") == 1
    assert json.loads(frame) == {"a": "has\nnewline", "b": [1, 2]}


def test_make_request_has_unique_ids_and_protocol():
    a = make_request("ping")
    b = make_request("ping")
    assert a["request_id"] != b["request_id"]
    assert a["protocol"] == 1
    assert a["params"] == {}


def test_make_response_shapes():
    assert make_response("x", status="success", result=1) == {
        "type": "response",
        "status": "success",
        "request_id": "x",
        "result": 1,
    }
    assert make_response("x", status="error", error="boom")["error"] == "boom"


def test_message_stream_splits_and_buffers_across_reads():
    """Frames arriving split across recv boundaries must reassemble."""
    server, client = socket.socketpair()
    try:
        stream = MessageStream(client)
        writer = threading.Thread(
            target=lambda: [
                server.sendall(b'{"status":"success","req'),
                server.sendall(b'uest_id":"a","result":1}\n{"status":"succ'),
                server.sendall(b'ess","request_id":"b","result":2}\n'),
            ]
        )
        writer.start()
        assert stream.read_message()["result"] == 1
        assert stream.read_message()["request_id"] == "b"
        writer.join()
    finally:
        server.close()
        client.close()


def test_message_stream_rejects_bad_json():
    server, client = socket.socketpair()
    try:
        server.sendall(b"not json\n")
        with pytest.raises(ProtocolError):
            MessageStream(client).read_message()
    finally:
        server.close()
        client.close()


def test_message_stream_rejects_non_object_frame():
    server, client = socket.socketpair()
    try:
        server.sendall(b"[1,2,3]\n")
        with pytest.raises(ProtocolError):
            MessageStream(client).read_message()
    finally:
        server.close()
        client.close()


def test_message_stream_detects_closed_connection():
    server, client = socket.socketpair()
    try:
        server.close()
        with pytest.raises(ProtocolError):
            MessageStream(client).read_message()
    finally:
        client.close()


# --------------------------------------------------------------------------
# fake add-on
# --------------------------------------------------------------------------


class FakeAddon:
    """Minimal stand-in for the Blender add-on socket server."""

    def __init__(self, responses=None, drop_connection=False, close_immediately=False):
        self.responses = responses or {}
        self.drop_connection = drop_connection
        self.close_immediately = close_immediately
        self.received = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                self.sock.settimeout(0.2)
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                if self.close_immediately:
                    continue
                stream = MessageStream(conn)
                try:
                    request = stream.read_message()
                except ProtocolError:
                    continue
                self.received.append(request)
                if self.drop_connection:
                    continue
                handler = self.responses.get(request["command"])
                if handler is None:
                    payload = make_response(
                        request["request_id"],
                        status="error",
                        error=f"unknown command {request['command']}",
                    )
                else:
                    try:
                        payload = make_response(
                            request["request_id"], status="success", result=handler(request["params"])
                        )
                    except Exception as exc:  # noqa: BLE001
                        payload = make_response(request["request_id"], status="error", error=str(exc))
                conn.sendall(encode_message(payload))

    def close(self):
        self._stop.set()
        self.sock.close()
        self._thread.join(timeout=2)


@contextmanager
def fake_addon(**kwargs):
    addon = FakeAddon(**kwargs)
    try:
        yield addon
    finally:
        addon.close()


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------


def test_client_calls_command_and_returns_result():
    with fake_addon(responses={"ping": lambda p: {"pong": True}}) as addon:
        assert BlenderClient(port=addon.port).call("ping") == {"pong": True}
        assert addon.received[0]["command"] == "ping"
        assert addon.received[0]["type"] == "command"


def test_client_raises_blender_error_on_error_response():
    def boom(params):
        raise ValueError("no object")

    with fake_addon(responses={"boom": boom}) as addon:
        with pytest.raises(BlenderError, match="no object"):
            BlenderClient(port=addon.port).call("boom")


def test_client_raises_on_unknown_command():
    with fake_addon() as addon:
        with pytest.raises(BlenderError, match="unknown command"):
            BlenderClient(port=addon.port).call("nope")


def test_client_reports_not_running_when_port_is_closed():
    with fake_addon() as addon:
        port = addon.port
    with pytest.raises(BlenderNotRunning) as excinfo:
        BlenderClient(port=port, connect_timeout=1.0).call("ping")
    assert "not reachable" in str(excinfo.value)
    assert "Start Server" in str(excinfo.value)


def test_connect_is_bounded_and_fast_on_a_dead_port():
    """Regression guard: an unbounded connect() blocks MCP discovery for minutes."""
    with fake_addon() as addon:
        port = addon.port
    start = time.monotonic()
    with pytest.raises(BlenderNotRunning):
        BlenderClient(port=port, connect_timeout=0.5).call("ping")
    assert time.monotonic() - start < 3.0


def test_status_returns_none_instead_of_raising():
    with fake_addon() as addon:
        port = addon.port
    assert BlenderClient(port=port, connect_timeout=0.5).status() is None


def test_status_returns_payload_when_up():
    with fake_addon(responses={"ping": lambda p: {"pong": True, "blender_version": "5.0.1"}}) as addon:
        assert BlenderClient(port=addon.port).status()["blender_version"] == "5.0.1"


def test_client_raises_on_dropped_connection():
    with fake_addon(drop_connection=True) as addon:
        with pytest.raises(BlenderError, match="truncated"):
            BlenderClient(port=addon.port, timeout=2.0).call("ping")


def test_params_round_trip():
    def echo(params):
        return {"got": params}

    with fake_addon(responses={"echo": echo}) as addon:
        result = BlenderClient(port=addon.port).call("echo", {"code": "1+1", "nested": {"k": [1]}})
        assert result == {"got": {"code": "1+1", "nested": {"k": [1]}}}


def test_screenshot_decodes_base64():
    import base64

    png = b"\x89PNG\r\n\x1a\nfake"
    with fake_addon(responses={"screenshot": lambda p: {"data": base64.b64encode(png).decode()}}) as addon:
        assert BlenderClient(port=addon.port).screenshot_png(512) == png


def test_screenshot_rejects_bad_base64():
    with fake_addon(responses={"screenshot": lambda p: {"data": "!!!not base64!!!"}}) as addon:
        with pytest.raises(BlenderError, match="undecodable"):
            BlenderClient(port=addon.port).screenshot_png()
