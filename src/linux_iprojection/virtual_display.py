"""Temporary Hyprland output; other desktops use the ScreenCast portal."""

import logging
import subprocess
import threading
import uuid

from .cast import PortalError

log = logging.getLogger(__name__)


class VirtualMonitor:
    def __init__(self):
        self.name = None
        self._lock = threading.RLock()

    def create(self):
        with self._lock:
            if self.name:
                raise PortalError("A virtual monitor is already active")
            name = f"iProjection-{uuid.uuid4().hex[:8]}"
            self.name = name
            try:
                result = subprocess.run(
                    ["hyprctl", "output", "create", "headless", name],
                    check=True, capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip() != "ok":
                    raise PortalError(f"Virtual monitor creation failed: {result.stdout.strip()}")
            except (OSError, subprocess.SubprocessError, PortalError) as exc:
                self.close()
                raise PortalError(f"Could not create an extended display: {exc}") from exc
            log.info("Created extended display %s; select it in the screen picker", name)
            return name

    def close(self):
        with self._lock:
            if not self.name:
                return
            try:
                result = subprocess.run(
                    ["hyprctl", "output", "remove", self.name],
                    check=True, capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip() != "ok":
                    raise PortalError(result.stdout.strip())
                self.name = None
            except (OSError, subprocess.SubprocessError, PortalError) as exc:
                log.warning("Could not remove extended display %s: %s", self.name, exc)
