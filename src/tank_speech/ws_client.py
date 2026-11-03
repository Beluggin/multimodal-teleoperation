"""ws_client.py — minimal stdlib WebSocket client (RFC 6455).

The speech stack is stdlib-only (it deploys to a bare Pi), and Python's
stdlib has no WebSocket client, so this is the smallest honest one:
handshake with accept-key verification, masked client frames, fragmented
message reassembly, ping->pong, and close handling. Text/binary only;
no extensions, no compression. Anything malformed raises WebSocketError
— the speech worker records it in status()["last_error"] and the robot
loop never sees it.
"""

import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlparse

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class WebSocketError(Exception):
    pass


def _accept_for(key_b64: str) -> str:
    digest = hashlib.sha1((key_b64 + _GUID).encode()).digest()
    return base64.b64encode(digest).decode()


class WebSocket:
    """One connected socket. Not thread-safe: one owner thread.

    mask_outgoing=True is the client role (frames MUST be masked);
    False is the server role (frames MUST NOT be masked). Receiving
    handles either, per RFC 6455.
    """

    def __init__(self, sock, reader, mask_outgoing=True):
        self._sock = sock
        self._reader = reader  # buffered file on the same socket
        self._mask_outgoing = mask_outgoing
        self._frag_op = None
        self._frag = bytearray()
        self._closed = False

    # -- sending ---------------------------------------------------------
    def _send_frame(self, opcode, payload=b""):
        if self._closed and opcode != OP_CLOSE:
            raise WebSocketError("socket is closed")
        n = len(payload)
        mask_bit = 0x80 if self._mask_outgoing else 0
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([mask_bit | n])
        elif n < 65536:
            head += bytes([mask_bit | 126]) + struct.pack(">H", n)
        else:
            head += bytes([mask_bit | 127]) + struct.pack(">Q", n)
        if self._mask_outgoing:
            mask = os.urandom(4)
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            head += mask
        self._sock.sendall(head + payload)

    def send_text(self, text: str):
        self._send_frame(OP_TEXT, text.encode())

    def send_binary(self, data: bytes):
        self._send_frame(OP_BINARY, bytes(data))

    def close(self):
        if self._closed:
            return
        try:
            self._send_frame(OP_CLOSE, b"")
        except (OSError, WebSocketError):
            pass
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def settimeout(self, timeout):
        self._sock.settimeout(timeout)

    # -- receiving -------------------------------------------------------
    def _read_exact(self, n):
        data = self._reader.read(n)
        if data is None or len(data) < n:
            raise WebSocketError("connection closed mid-frame")
        return data

    def recv_message(self):
        """Next complete message: ("text", str) | ("binary", bytes).

        Returns ("close", bytes) when the peer closes. Raises
        WebSocketError on protocol errors and socket.timeout on timeout
        (callers use the timeout as their idle poll).
        """
        while True:
            head = self._reader.read(2)
            if not head or len(head) < 2:
                raise WebSocketError("connection closed")
            fin, opcode = bool(head[0] & 0x80), head[0] & 0x0F
            masked, n = bool(head[1] & 0x80), head[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = bytearray(self._read_exact(n)) if n else bytearray()
            if masked:
                for i in range(len(payload)):
                    payload[i] ^= mask[i % 4]
            if opcode == OP_PING:
                self._send_frame(OP_PONG, bytes(payload))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                self._closed = True
                return "close", bytes(payload)
            if opcode in (OP_TEXT, OP_BINARY):
                if fin:
                    return self._decode(opcode, bytes(payload))
                self._frag_op, self._frag = opcode, bytearray(payload)
                continue
            if opcode == 0x0:  # continuation
                if self._frag_op is None:
                    raise WebSocketError("continuation without start")
                self._frag += payload
                if fin:
                    op, data = self._frag_op, bytes(self._frag)
                    self._frag_op, self._frag = None, bytearray()
                    return self._decode(op, data)
                continue
            raise WebSocketError(f"unknown opcode {opcode}")

    @staticmethod
    def _decode(opcode, payload):
        if opcode == OP_TEXT:
            return "text", payload.decode("utf-8", errors="replace")
        return "binary", payload


def ws_connect(url, headers=None, timeout=15.0):
    """Open a ws:// or wss:// connection. Raises WebSocketError."""
    parts = urlparse(url or "")
    if parts.scheme not in ("ws", "wss"):
        raise WebSocketError(f"expected ws(s):// URL, got {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise WebSocketError("URL has no host")
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    raw = socket.create_connection((host, port), timeout=timeout)
    if parts.scheme == "wss":
        raw = ssl.create_default_context().wrap_socket(
            raw, server_hostname=host)
    reader = raw.makefile("rb")
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}",
             "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    raw.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    status = reader.readline(65536).decode("latin1").strip()
    if "101" not in status:
        raw.close()
        raise WebSocketError(f"handshake refused: {status!r}")
    resp_headers = {}
    while True:
        line = reader.readline(65536).decode("latin1").strip()
        if not line:
            break
        if ":" in line:
            name, value = line.split(":", 1)
            resp_headers[name.strip().lower()] = value.strip()
    if resp_headers.get("sec-websocket-accept") != _accept_for(key):
        raw.close()
        raise WebSocketError("handshake accept key mismatch")
    return WebSocket(raw, reader)


def accept_websocket(sock, reader, headers):
    """Server side: answer an Upgrade request on an accepted socket.

    `headers` maps lower-cased request header names to values; `reader`
    is the socket's buffered file positioned after the request headers.
    Returns a server-role WebSocket. Raises WebSocketError (after
    writing a 400) when the upgrade headers are missing or wrong.
    """
    key = headers.get("sec-websocket-key", "")
    upgrade = headers.get("upgrade", "").lower()
    if not key or upgrade != "websocket":
        try:
            sock.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                         b"Content-Length: 0\r\n\r\n")
        except OSError:
            pass
        raise WebSocketError("missing websocket upgrade headers")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {_accept_for(key)}\r\n\r\n")
    sock.sendall(response.encode())
    return WebSocket(sock, reader, mask_outgoing=False)
