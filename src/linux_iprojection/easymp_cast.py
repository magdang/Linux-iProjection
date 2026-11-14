"""Wayland/X11 capture feeding the native EasyMP JPEG session."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time

import gi
from PIL import Image

gi.require_version("GstVideo", "1.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst, GstVideo  # noqa: E402

from .cast import (  # noqa: E402
    TEST_PATTERNS,
    StreamStats,
    UserCancelledError,
    _close_session,
    _ensure_gst,
    _request_portal_stream,
)
from .easymp import EasyMPClient  # noqa: E402
from .protocol import ProjectorError  # noqa: E402

log = logging.getLogger(__name__)


class EasyMPCaster:
    def __init__(self, on_stats=None, on_error=None, fps=15, stream_quality="balanced"):
        self.on_stats, self.on_error = on_stats, on_error
        self.fps = min(max(fps, 1), 24)
        self.last_error = None
        self.user_cancelled = False
        self._is_casting = False
        self._stop = threading.Event()
        self._first_frame = threading.Event()
        self._frames = queue.Queue(maxsize=1)
        self._worker = self._pipeline = self._client = None
        self._portal_session_handle = None
        self._pipewire_fd = None
        self._bus_handler = None
        self.active_pattern = None
        self.quality = {"low_latency": 65, "balanced": 85, "high_quality": 95}[stream_quality]

    @property
    def is_casting(self):
        return self._is_casting and not self._stop.is_set()

    async def start(self, target, virtual=False):
        if virtual:
            self.last_error = "EasyMP currently mirrors a selected screen or window; virtual display creation is not implemented."
            return False
        return await self._start(target)

    async def start_test_pattern(self, target, pattern="smpte"):
        if pattern not in TEST_PATTERNS:
            raise ValueError(f"Unknown test pattern: {pattern}")
        return await self._start(target, pattern)

    async def _start(self, target, pattern=None):
        if self._client is not None or (self._worker and self._worker.is_alive()):
            raise ProjectorError("Stop the previous EasyMP session before starting another")
        self._stop.clear()
        self._first_frame.clear()
        while not self._frames.empty():
            self._frames.get_nowait()
        self.last_error = None
        self.user_cancelled = False
        _ensure_gst()
        try:
            if pattern is None:
                node, self._portal_session_handle = await _request_portal_stream()
                if self._stop.is_set():
                    return False
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                reply, fds = bus.call_with_unix_fd_list_sync(
                    "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                    "org.freedesktop.portal.ScreenCast", "OpenPipeWireRemote",
                    GLib.Variant("(oa{sv})", (self._portal_session_handle, {})),
                    GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None,
                )
                self._pipewire_fd = fds.get(reply.unpack()[0])
                source = f"pipewiresrc fd={self._pipewire_fd} path={node} do-timestamp=true"
            else:
                source = f"videotestsrc is-live=true pattern={TEST_PATTERNS[pattern]}"
            client = EasyMPClient(target.host, keyword=target.password)
            client.quality = self.quality
            self._client = client
            connecting = asyncio.create_task(asyncio.to_thread(client.connect))
            try:
                await asyncio.shield(connecting)
            except asyncio.CancelledError:
                try:
                    await connecting
                finally:
                    await asyncio.to_thread(client.close)
                raise
            if self._stop.is_set():
                return False
            width, height = client.identity.width, client.identity.height
            pipeline = (
                f"{source} ! videoconvert ! videoscale add-borders=true ! videorate ! "
                f"video/x-raw,format=RGB,width={width},height={height},pixel-aspect-ratio=1/1,framerate={self.fps}/1 ! "
                "appsink name=frames emit-signals=true max-buffers=1 drop=true sync=false"
            )
            self._pipeline = Gst.parse_launch(pipeline)
            self._pipeline.get_by_name("frames").connect("new-sample", self._sample)
            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            self._bus_handler = bus.connect("message", self._message)
            if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise ProjectorError("Screen capture pipeline could not start")
            self._worker = threading.Thread(target=self._send_frames)
            self._worker.start()
            await asyncio.to_thread(self._first_frame.wait, 8)
            if self._stop.is_set() or not client.frames_sent:
                raise ProjectorError(self.last_error or "No screen frame was delivered to the EasyMP session")
            self.active_pattern = pattern
            self._is_casting = True
            log.info("EasyMP session accepted and first JPEG frame sent to %s", target.host)
            return True
        except UserCancelledError:
            self.user_cancelled = True
            self.last_error = "Screen sharing cancelled by user"
            return False
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("EasyMP casting failed")
            return False
        finally:
            if not self._is_casting:
                self.stop()

    def _sample(self, sink):
        try:
            sample = sink.emit("pull-sample")
            info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
            buffer = sample.get_buffer()
            image = Image.frombytes("RGB", (info.width, info.height),
                                    buffer.extract_dup(0, buffer.get_size()), "raw", "RGB", info.stride[0])
            try:
                self._frames.put_nowait(image)
            except queue.Full:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                self._frames.put_nowait(image)
            return Gst.FlowReturn.OK
        except Exception as exc:
            self.last_error = f"Screen frame conversion failed: {exc}"
            self._stop.set()
            self._first_frame.set()
            return Gst.FlowReturn.ERROR

    def _send_frames(self):
        client = self._client
        last = time.monotonic()
        old_bytes = old_frames = 0
        try:
            while not self._stop.is_set():
                client.service()
                try:
                    image = self._frames.get(timeout=0.03)
                except queue.Empty:
                    continue
                client.send_image(image)
                self._first_frame.set()
                now = time.monotonic()
                if now - last >= 1:
                    if self.on_stats:
                        self.on_stats(StreamStats(
                            bitrate_kbps=(client.bytes_sent - old_bytes) * 8 / (now - last) / 1000,
                            fps=(client.frames_sent - old_frames) / (now - last), audio_active=False,
                        ))
                    last, old_bytes, old_frames = now, client.bytes_sent, client.frames_sent
        except Exception as exc:
            if not self._stop.is_set():
                self.last_error = f"EasyMP stream ended: {exc}"
                log.exception(self.last_error)
                if self.on_error:
                    self.on_error(self.last_error)
                GLib.idle_add(self.stop)
        finally:
            self._stop.set()
            self._first_frame.set()
            client.close()

    def _message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.last_error = f"Screen capture failed: {error.message}"
            log.error("%s: %s", self.last_error, debug)
            if self.on_error:
                self.on_error(self.last_error)
            self.stop()
        elif message.type == Gst.MessageType.EOS:
            self.stop()

    def stop(self):
        self._stop.set()
        self._first_frame.set()
        self._is_casting = False
        if self._pipeline:
            bus = self._pipeline.get_bus()
            if self._bus_handler:
                bus.disconnect(self._bus_handler)
                bus.remove_signal_watch()
                self._bus_handler = None
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=0.1)
        elif self._client:
            self._client.close()
        if not self._worker or not self._worker.is_alive():
            self._client = None
        _close_session(self._portal_session_handle)
        self._portal_session_handle = None
        if self._pipewire_fd is not None:
            os.close(self._pipewire_fd)
            self._pipewire_fd = None
        self.active_pattern = None
