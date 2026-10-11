"""Wire protocol shared by the Blender add-on socket server and the MCP client.

Transport: TCP, newline-delimited UTF-8 JSON. One request -> one response.

Request::

    {"type": "command", "command": "get_scene_info", "params": {},
     "request_id": "5f2c...", "protocol": 1}

Response::

    {"type": "response", "status": "success"|"error", "request_id": "5f2c...",
     "result": {...}, "error": "traceback"}

The format is deliberately dumb so that the Blender side needs zero
third-party imports, and so a human can drive the add-on with ``nc``.
"""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
PROTOCOL_VERSION = 1

#: Hard ceiling on a single framed message (32 MiB). Screenshots come back
#: base64-encoded, so this comfortably covers a full-HD PNG.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class ProtocolError(Exception):
    """Malformed frame, oversized message, or peer closed mid-exchange."""


def encode_message(payload: dict[str, Any]) -> bytes:
    """Serialise ``payload`` as one newline-terminated JSON frame."""
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    if b"\n" in data[:-1]:
        # json.dumps escapes newlines inside strings, so this can only happen
        # if a key was built with raw control characters -- refuse rather than
        # desynchronise the stream.
        raise ProtocolError("message contains a raw newline and cannot be framed")
    return data + b"\n"


def _json_default(value: Any) -> Any:
    """Best-effort coercion for objects json cannot natively encode."""
    for attr in ("to_dict", "to_json"):
        method = getattr(value, attr, None)
        if callable(method):
            return method()
    return repr(value)


def make_request(command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "command",
        "command": command,
        "params": params or {},
        "request_id": uuid.uuid4().hex,
        "protocol": PROTOCOL_VERSION,
    }


def make_response(
    request_id: str | None,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "response", "status": status, "request_id": request_id}
    if status == "success":
        payload["result"] = result
    else:
        payload["error"] = error or "unknown error"
    return payload


class MessageStream:
    """Incremental newline-JSON reader over a blocking socket.

    ``recv`` is wrapped in a loop because TCP is a stream: a single read can
    return half a frame or three frames at once. Leftover bytes stay buffered
    for the next call.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = bytearray()

    def read_message(self) -> dict[str, Any]:
        while True:
            index = self._buffer.find(b"\n")
            if index != -1:
                raw = bytes(self._buffer[:index])
                del self._buffer[: index + 1]
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError(f"invalid JSON frame: {exc}") from exc
                if not isinstance(message, dict):
                    raise ProtocolError("frame is not a JSON object")
                return message

            if len(self._buffer) > MAX_MESSAGE_BYTES:
                raise ProtocolError(f"message exceeds {MAX_MESSAGE_BYTES} bytes")

            chunk = self._sock.recv(65536)
            if not chunk:
                raise ProtocolError("peer closed the connection mid-message")
            self._buffer.extend(chunk)
