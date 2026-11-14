"""Epson EasyMP TCP control and tiled JPEG transport.

Wire format adapted from LibreMP and epson-projector-linux (MIT).
See THIRD_PARTY_NOTICES.md and docs/EB1945W_SUPPORT.md for evidence and limits.
"""

from __future__ import annotations

import io
import logging
import select
import socket
import struct
import time
from dataclasses import dataclass

from PIL import Image

from .protocol import ProjectorError

log = logging.getLogger(__name__)
HEADER = struct.Struct("<8s4sII")
MAX_CONTROL_PAYLOAD = 65536


def control_packet(ip: str, command: int, payload: bytes = b"") -> bytes:
    return HEADER.pack(b"EEMP0100", socket.inet_aton(ip), command, len(payload)) + payload


def read_message(sock: socket.socket, deadline: float) -> tuple[int, bytes]:
    def exact(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("EasyMP response timed out")
            sock.settimeout(remaining)
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ProjectorError("Projector closed the EasyMP control connection")
            data.extend(chunk)
        return bytes(data)

    magic, _, command, size = HEADER.unpack(exact(HEADER.size))
    if magic != b"EEMP0100" or size > MAX_CONTROL_PAYLOAD:
        raise ProjectorError("Invalid EasyMP control header or payload length")
    return command, exact(size)


@dataclass
class ProjectorIdentity:
    name: bytes = b""
    mac: bytes = b""
    width: int = 1024
    height: int = 768
    tile_width: int = 624
    tile_height: int = 416
    flags: bytes = b""
    jpeg: bool = False

    def update(self, command: int, payload: bytes) -> None:
        if command == 3:
            if len(payload) < 54:
                raise ProjectorError("Truncated EasyMP projector identity")
            self.name = payload[4:36].split(b"\0", 1)[0]
            if not self.mac:
                self.mac = payload[48:54]
        elif command == 0x15:
            if len(payload) < 30:
                raise ProjectorError("Truncated EasyMP capability header")
            self.mac = payload[:6]
            end = 30 + int.from_bytes(payload[26:28], "big")
            if end > len(payload):
                raise ProjectorError("Truncated EasyMP capability records")
            offset = 30
            while offset + 2 <= end:
                kind, size = payload[offset:offset + 2]
                offset += 2
                if kind == 0:
                    break
                if offset + size > end:
                    raise ProjectorError("Truncated EasyMP capability record")
                data = payload[offset:offset + size]
                offset += size
                if kind == 3 and size >= 4:
                    self.width, self.height = struct.unpack_from("<HH", data)
                    if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
                        raise ProjectorError("Unsupported EasyMP frame dimensions")
                elif kind == 5:
                    for at in range(0, size - 21, 22):
                        if data[at:at + 2] == b"\x07\x0b":
                            self.jpeg = True
                            w, h = struct.unpack_from("<HH", data, at + 14)
                            if w < 16 or h < 16:
                                raise ProjectorError("Invalid EasyMP JPEG tile dimensions")
                            self.tile_width = min(w, 624) // 16 * 16
                            self.tile_height = min(h, 416) // 16 * 16
                elif kind == 8:
                    self.flags = data


def registration_packet(ip: str) -> bytes:
    return control_packet(ip, 2, bytes.fromhex("007f0000b0f8ef5314000000") + bytes(36))


def login_packet(ip: str, host: str, identity: ProjectorIdentity, keyword: str = "") -> bytes:
    if keyword and (len(keyword) != 4 or not keyword.isascii() or not keyword.isdigit()):
        raise ValueError("The EasyMP Projector Keyword must contain exactly four ASCII digits")
    if len(identity.mac) != 6 or not any(identity.mac) or not identity.name:
        raise ProjectorError("Projector did not provide an EasyMP name and MAC address")
    body = bytearray.fromhex(
        "0100000000000000000020f37fffff0000000000000201030004000320200001ff00ff00ff00000810000000010c0000"
    )
    struct.pack_into("<HH", body, 24, identity.width, identity.height)
    body += identity.mac + keyword.encode("ascii").ljust(16, b"\0") + socket.inet_aton(ip)
    return control_packet(ip, 4, body)


def video_frame(ip: str, tiles: list[tuple[int, int, int, int, bytes]], size: tuple[int, int]) -> bytes:
    prefix = b"EPRD0600" + socket.inet_aton(ip) + bytes(4)
    width, height = size
    payload = bytearray(struct.pack(">I", len(tiles)))
    for x, y, w, h, jpeg in tiles:
        n = len(jpeg)
        if not (0 <= x < width and 0 <= y < height and 0 < w <= width - x and 0 < h <= height - y):
            raise ValueError("JPEG tile lies outside the negotiated frame")
        if not (0 < n < 1 << 21) or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("Invalid or oversized EasyMP JPEG tile")
        payload += struct.pack(">HHHHI", x, y, w, h, 7)
        payload += bytes((0x90, 0x80 | (n & 127), 0x80 | ((n >> 7) & 127), n >> 14)) + jpeg
    return prefix + struct.pack(">I", len(payload)) + payload


class EasyMPClient:
    """One accepted projection session; no retries, takeover, or keyword guessing."""

    def __init__(self, host: str, keyword: str = "", control_port: int = 3620, video_port: int = 3621):
        self.host = host
        self.keyword = keyword
        self.control_port = control_port
        self.video_port = video_port
        self.identity = ProjectorIdentity()
        self.ip = ""
        self.control = self.video = self.aux = None
        self.accepted = False
        self.bytes_sent = self.frames_sent = 0
        self.quality = 85
        self._last_keepalive = 0.0

    def _open(self, port):
        sock = socket.create_connection((self.host, port), timeout=3)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(3)
        return sock

    def inspect(self) -> ProjectorIdentity:
        with self._open(self.control_port) as sock:
            self.ip = sock.getsockname()[0]
            sock.sendall(registration_packet(self.ip))
            seen = set()
            deadline = time.monotonic() + 3
            while not {3, 0x15}.issubset(seen):
                command, payload = read_message(sock, deadline)
                self.identity.update(command, payload)
                seen.add(command)
        if not self.identity.jpeg:
            raise ProjectorError("Projector did not advertise the supported EasyMP JPEG encoding")
        return self.identity

    def _handle(self, command, payload):
        if command == 5:
            if len(payload) < 54:
                raise ProjectorError("Truncated EasyMP connection reply")
            self.accepted = True
        elif command in (6, 7, 0x111):
            raise ProjectorError(f"Projector ended or rejected EasyMP streaming (0x{command:04x})")

    def _wait(self, expected):
        deadline = time.monotonic() + 5
        while True:
            command, payload = read_message(self.control, deadline)
            self._handle(command, payload)
            if command == expected:
                return

    def connect(self):
        try:
            self.inspect()
            self.control = self._open(self.control_port)
            self.control.sendall(login_packet(self.ip, self.control.getpeername()[0], self.identity, self.keyword))
            self._wait(5)
            self.video = self._open(self.video_port)
            self.aux = self._open(self.video_port)
            size = struct.pack(">HH", self.identity.width, self.identity.height)
            meta = b"\xc8\0\0\0" + size + bytes.fromhex("20200001ff00ff00ff00100800000000")
            self.video.sendall(b"EPRD0600" + socket.inet_aton(self.ip) + bytes(4)
                               + struct.pack("<I", len(meta)) + meta)
            self._wait(0x16)
            self._last_keepalive = time.monotonic()
            log.info("EasyMP session accepted: %s, %dx%d, TCP video %d", self.host,
                     self.identity.width, self.identity.height, self.video_port)
        except BaseException:
            self.close()
            raise

    def service(self):
        if select.select([self.control], [], [], 0)[0]:
            self._handle(*read_message(self.control, time.monotonic() + 3))
        now = time.monotonic()
        if now - self._last_keepalive >= 1:
            self.control.sendall(control_packet(self.ip, 10))
            self._last_keepalive = now

    def send_image(self, image: Image.Image):
        width, height = self.identity.width, self.identity.height
        if image.size != (width, height):
            raise ValueError("Capture dimensions differ from the negotiated EasyMP frame")
        tiles = []
        for y in range(0, height, self.identity.tile_height):
            for x in range(0, width, self.identity.tile_width):
                right, bottom = min(x + self.identity.tile_width, width), min(y + self.identity.tile_height, height)
                encoded = io.BytesIO()
                image.crop((x, y, right, bottom)).save(encoded, "JPEG", quality=self.quality, subsampling=2)
                tiles.append((x, y, right - x, bottom - y, encoded.getvalue()))
        frame = video_frame(self.ip, tiles, (width, height))
        self.video.sendall(frame)
        self.frames_sent += 1
        self.bytes_sent += len(frame)

    def close(self):
        try:
            if self.accepted and self.control:
                self.control.sendall(control_packet(self.ip, 6))
                deadline = time.monotonic() + 3
                while read_message(self.control, deadline)[0] != 7:
                    pass
        except (OSError, ProjectorError):
            pass
        finally:
            self.accepted = False
            for sock in (self.video, self.aux, self.control):
                if sock:
                    sock.close()
            self.video = self.aux = self.control = None
