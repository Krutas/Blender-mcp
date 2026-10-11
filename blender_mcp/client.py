"""Blocking client for the Blender add-on socket server.

Design rule learned the hard way: **never connect during MCP server startup.**
An MCP client calls ``initialize`` + ``tools/list`` during discovery, and a
``socket.connect()`` to a firewalled (SYN-dropped) port blocks for the OS TCP
timeout -- minutes -- which makes the whole server look dead. Every connection
here is lazy (opened on the first tool call) and carries an explicit timeout,
so discovery always completes instantly whether or not Blender is running.
"""

from __future__ import annotations

import base64
import socket
from typing import Any

from .protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MessageStream,
    ProtocolError,
    encode_message,
    make_request,
)


class BlenderError(RuntimeError):
    """The add-on answered with ``status: error``."""


class BlenderNotRunning(BlenderError):
    """Could not reach the add-on socket at all."""


class BlenderClient:
    """Thin request/response client, one socket per call."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 60.0,
        connect_timeout: float = 4.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connect_timeout = connect_timeout

    # -- low level ---------------------------------------------------------

    def _open(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Bounded on purpose -- see module docstring.
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise BlenderNotRunning(
                f"Blender add-on not reachable at {self.host}:{self.port} ({exc}). "
                "In Blender: 3D Viewport > Sidebar (N) > Blender MCP > Start Server."
            ) from exc
        sock.settimeout(self.timeout)
        return sock

    def call(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Send one command and return its ``result``.

        Raises :class:`BlenderNotRunning` if the add-on is unreachable and
        :class:`BlenderError` if it answered with an error.
        """
        sock = self._open()
        try:
            sock.sendall(encode_message(make_request(command, params)))
            try:
                message = MessageStream(sock).read_message()
            except (ProtocolError, socket.timeout, OSError) as exc:
                raise BlenderError(f"malformed or truncated response from Blender: {exc}") from exc
        finally:
            try:
                sock.close()
            except OSError:
                pass

        if message.get("status") != "success":
            error = message.get("error") or "Blender reported an unknown error"
            detail = message.get("traceback")
            if detail and detail.strip() != error.strip():
                # Keep the short message as the exception text (that is what the
                # agent reads) and hang the full traceback off the exception.
                exc = BlenderError(error)
                exc.traceback = detail
                raise exc
            raise BlenderError(error)
        return message.get("result")

    # -- convenience -------------------------------------------------------

    def status(self) -> dict[str, Any] | None:
        """Return the add-on's ``ping`` payload, or ``None`` if it is not up.

        Deliberately swallows errors: this is the health probe used before
        every tool call and by the ``blender_status`` tool.
        """
        try:
            return self.call("ping")
        except BlenderError:
            return None

    def screenshot(self, max_size: int = 1024) -> tuple[bytes, dict[str, Any]]:
        """Fetch a screenshot as ``(png_bytes, metadata)``.

        The metadata carries ``width``, ``height``, which render ``strategy``
        won, the ``lit_fraction`` of the frame, and a ``warning`` when every
        strategy produced a near-black image.
        """
        result = self.call("screenshot", {"max_size": max_size})
        if not isinstance(result, dict):
            raise BlenderError("add-on returned no screenshot data")
        encoded = result.get("data")
        if not isinstance(encoded, str):
            raise BlenderError("add-on returned no screenshot data")
        try:
            png = base64.b64decode(encoded)
        except (ValueError, TypeError) as exc:
            raise BlenderError(f"add-on returned undecodable base64: {exc}") from exc
        meta = {key: value for key, value in result.items() if key != "data"}
        return png, meta

    def screenshot_png(self, max_size: int = 1024) -> bytes:
        """Fetch a screenshot as raw PNG bytes."""
        return self.screenshot(max_size)[0]
