"""Native EasyMP against sanitized hardware replies and a local TCP projector."""

import io
import socket
import struct
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from linux_iprojection.easymp import (
    HEADER,
    EasyMPClient,
    ProjectorIdentity,
    control_packet,
    login_packet,
    read_message,
    registration_packet,
    video_frame,
)
from linux_iprojection.protocol import ProjectorError

REGISTRATION = bytes.fromhex((Path(__file__).parent / "fixtures/easymp_1945w_registration.hex").read_text())


def identity():
    result = ProjectorIdentity()
    offset = 0
    while offset < len(REGISTRATION):
        _, _, command, size = HEADER.unpack_from(REGISTRATION, offset)
        result.update(command, REGISTRATION[offset + 20:offset + 20 + size])
        offset += 20 + size
    return result


def test_hardware_capabilities_and_login():
    projector = identity()
    assert (projector.width, projector.height) == (1280, 800)
    assert (projector.tile_width, projector.tile_height) == (624, 416)
    assert projector.name == b"TEST1945W"
    assert len(registration_packet("127.0.0.1")) == 68
    login = login_packet("127.0.0.1", "127.0.0.1", projector, "1234")
    assert HEADER.unpack_from(login)[2:] == (4, len(login) - 20)
    assert struct.unpack_from("<HH", login, 44) == (1280, 800)
    assert login[68:74] == projector.mac
    assert login[74:90] == b"1234" + bytes(12)


@pytest.mark.parametrize("keyword", ["123", "12345", "test", "１２３４", "12\n4"])
def test_invalid_keyword(keyword):
    with pytest.raises(ValueError, match="four ASCII"):
        login_packet("127.0.0.1", "127.0.0.1", identity(), keyword)


@pytest.mark.parametrize("payload", [b"", bytes(29), bytes(26) + b"\xff\xff\0\0"])
def test_truncated_capabilities(payload):
    with pytest.raises(ProjectorError, match="Truncated"):
        ProjectorIdentity().update(0x15, payload)


def test_fragmented_and_coalesced_control_messages():
    a, b = socket.socketpair()
    wire = control_packet("127.0.0.1", 0x16, b"data") + control_packet("127.0.0.1", 10)

    def send():
        with b:
            for byte in wire:
                b.sendall(bytes([byte]))

    thread = threading.Thread(target=send)
    thread.start()
    with a:
        assert read_message(a, time.monotonic() + 2) == (0x16, b"data")
        assert read_message(a, time.monotonic() + 2) == (10, b"")
    thread.join(timeout=2)


@pytest.mark.parametrize("wire", [b"wrong", b"EEMP0100" + bytes(12), control_packet("127.0.0.1", 2, b"abc")[:-1]])
def test_closed_and_truncated_messages(wire):
    a, b = socket.socketpair()
    with a, b:
        b.sendall(wire)
        b.shutdown(socket.SHUT_WR)
        if len(wire) == 20:
            assert read_message(a, time.monotonic() + 1) == (0, b"")
        with pytest.raises(ProjectorError, match="closed"):
            read_message(a, time.monotonic() + 1)


def test_rejects_oversized_control_payload():
    a, b = socket.socketpair()
    with a, b:
        b.sendall(HEADER.pack(b"EEMP0100", bytes(4), 3, 65537))
        with pytest.raises(ProjectorError, match="Invalid"):
            read_message(a, time.monotonic() + 1)


def test_control_timeout():
    a, b = socket.socketpair()
    with a, b, pytest.raises(TimeoutError):
        read_message(a, time.monotonic() + 0.01)


@pytest.fixture
def fake_projector():
    control = socket.create_server(("127.0.0.1", 0))
    video = socket.create_server(("127.0.0.1", 0))
    control.settimeout(3)
    video.settimeout(3)
    errors = []
    seen = {"frame": None, "goodbye": False, "heartbeat": False}

    def serve():
        try:
            reg, _ = control.accept()
            with reg:
                assert read_message(reg, time.monotonic() + 3)[0] == 2
                for at in range(0, len(REGISTRATION), 7):
                    reg.sendall(REGISTRATION[at:at + 7])
            auth, _ = control.accept()
            with auth:
                assert read_message(auth, time.monotonic() + 3)[0] == 4
                auth.sendall(control_packet("127.0.0.1", 5, REGISTRATION[20:94]))
                stream, _ = video.accept()
                aux, _ = video.accept()
                with stream, aux:
                    stream.settimeout(3)
                    header = stream.recv(20, socket.MSG_WAITALL)
                    assert header[:8] == b"EPRD0600"
                    size = int.from_bytes(header[16:20], "little")
                    meta = stream.recv(size, socket.MSG_WAITALL)
                    assert meta[:8] == bytes.fromhex("c800000005000320")
                    auth.sendall(control_packet("127.0.0.1", 0x16, bytes(4)))
                    header = stream.recv(20, socket.MSG_WAITALL)
                    if header:
                        size = int.from_bytes(header[16:20], "big")
                        seen["frame"] = stream.recv(size, socket.MSG_WAITALL)
                    while True:
                        command, _ = read_message(auth, time.monotonic() + 4)
                        if command == 10:
                            seen["heartbeat"] = True
                        elif command == 6:
                            time.sleep(0.05)
                            auth.sendall(control_packet("127.0.0.1", 7))
                            seen["goodbye"] = True
                            break
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    yield control.getsockname()[1], video.getsockname()[1], seen
    worker.join(timeout=5)
    control.close()
    video.close()
    assert not worker.is_alive()
    assert not errors, errors


def test_native_session_stream_heartbeat_and_goodbye(fake_projector):
    control, video, seen = fake_projector
    client = EasyMPClient("127.0.0.1", control_port=control, video_port=video)
    try:
        client.connect()
        assert client.accepted
        client.send_image(Image.new("RGB", (1280, 800), "red"))
        client._last_keepalive -= 2
        client.service()
        assert client.frames_sent == 1
    finally:
        client.close()
    assert not client.accepted
    assert seen["goodbye"]
    assert seen["heartbeat"]
    payload = seen["frame"]
    count = struct.unpack_from(">I", payload)[0]
    assert count == 6
    offset = 4
    area = 0
    for _ in range(count):
        x, y, w, h, encoding = struct.unpack_from(">HHHHI", payload, offset)
        tag, a, b, c = payload[offset + 12:offset + 16]
        size = (a & 127) | ((b & 127) << 7) | (c << 14)
        assert tag == 0x90 and encoding == 7
        image = Image.open(io.BytesIO(payload[offset + 16:offset + 16 + size]))
        assert image.size == (w, h)
        assert image.getpixel((0, 0))[0] > 240
        assert x + w <= 1280 and y + h <= 800
        area += w * h
        offset += 16 + size
    assert area == 1280 * 800
    assert offset == len(payload)


def test_refused_and_malformed_login():
    client = EasyMPClient("127.0.0.1")
    for command, payload in ((7, b""), (5, b"short"), (0x111, b"")):
        with pytest.raises(ProjectorError):
            client._handle(command, payload)
        assert not client.accepted


def test_video_rejects_out_of_bounds_or_invalid_jpeg():
    for tile in [(1280, 0, 16, 16, b"\xff\xd8\xff\xd9"), (0, 0, 16, 16, b"not jpeg")]:
        with pytest.raises(ValueError):
            video_frame("127.0.0.1", [tile], (1280, 800))


@pytest.mark.asyncio
async def test_gstreamer_capture_to_native_jpeg_worker(mocker):
    from linux_iprojection.cast import CastTarget
    from linux_iprojection.easymp_cast import EasyMPCaster

    client = mocker.Mock()
    client.identity = identity()
    client.frames_sent = client.bytes_sent = 0

    def send(image):
        assert image.mode == "RGB" and image.size == (1280, 800)
        client.frames_sent += 1
        client.bytes_sent += 1000

    client.send_image.side_effect = send
    mocker.patch("linux_iprojection.easymp_cast.EasyMPClient", return_value=client)
    caster = EasyMPCaster()
    try:
        assert await caster.start_test_pattern(CastTarget(host="127.0.0.1"))
        assert caster.is_casting
        assert client.frames_sent >= 1
        client.connect.assert_called_once()
    finally:
        caster.stop()
        caster._worker.join(timeout=2)
    assert not caster.is_casting
    assert not caster._worker.is_alive()
    assert caster._pipeline is None
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_portal_cancel_does_not_connect(mocker):
    from linux_iprojection.cast import CastTarget, UserCancelledError
    from linux_iprojection.easymp_cast import EasyMPCaster

    mocker.patch("linux_iprojection.easymp_cast._request_portal_stream", side_effect=UserCancelledError)
    client = mocker.patch("linux_iprojection.easymp_cast.EasyMPClient")
    caster = EasyMPCaster()
    assert not await caster.start(CastTarget(host="127.0.0.1"))
    assert caster.user_cancelled
    client.assert_not_called()


@pytest.mark.asyncio
async def test_stop_during_picker_closes_returned_portal(mocker):
    from linux_iprojection.cast import CastTarget
    from linux_iprojection.easymp_cast import EasyMPCaster

    caster = EasyMPCaster()

    async def portal():
        caster.stop()
        return 42, "test-session"

    mocker.patch("linux_iprojection.easymp_cast._request_portal_stream", side_effect=portal)
    close = mocker.patch("linux_iprojection.easymp_cast._close_session")
    client = mocker.patch("linux_iprojection.easymp_cast.EasyMPClient")
    assert not await caster.start(CastTarget(host="127.0.0.1"))
    assert any(call.args == ("test-session",) for call in close.call_args_list)
    client.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_failure_releases_accepted_session(mocker):
    from linux_iprojection.cast import CastTarget
    from linux_iprojection.easymp_cast import EasyMPCaster

    client = mocker.Mock()
    client.identity = identity()
    mocker.patch("linux_iprojection.easymp_cast.EasyMPClient", return_value=client)
    mocker.patch("linux_iprojection.easymp_cast.Gst.parse_launch", side_effect=ValueError("invalid pipeline"))
    caster = EasyMPCaster()
    assert not await caster.start_test_pattern(CastTarget(host="127.0.0.1"))
    assert "invalid pipeline" in caster.last_error
    client.close.assert_called_once()
    assert caster._client is None
