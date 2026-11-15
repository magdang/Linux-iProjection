"""Own optional AirPlay/Android receiver processes; projection still uses consent."""

import ipaddress
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def executable(name):
    found = shutil.which(name)
    local = Path(sys.prefix) / "bin" / name
    if found:
        return found
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise RuntimeError(f"Install {name} to use phone mirroring")


def _adb(*args, input=None):
    try:
        result = subprocess.run([executable("adb"), *args], input=input, text=True,
                                capture_output=True, timeout=30, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()[-1024:]
        if input:
            detail = detail.replace(input.strip(), "[code]")
        raise RuntimeError(f"ADB failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Android connection timed out; check Wireless debugging and the Wi-Fi network") from exc
    return result.stdout.strip()


def _endpoint(value):
    try:
        address, port = value.strip().rsplit(":", 1)
        address = ipaddress.IPv4Address(address)
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Enter the phone's IPv4 address and port, such as 192.168.1.20:37123") from exc
    return f"{address}:{int(port)}"


def pair_android(pairing_address, code, connection_address):
    pairing_address, connection_address = _endpoint(pairing_address), _endpoint(connection_address)
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError("Enter the six-digit code shown by Android Wireless debugging")
    result = _adb("pair", pairing_address, input=code + "\n")
    if "Successfully paired" not in result:
        raise RuntimeError("Android did not confirm pairing; check the code and pairing port")
    _adb("connect", connection_address)
    if _adb("-s", connection_address, "get-state") != "device":
        raise RuntimeError("Paired, but the phone is not connected; use the connection port from Wireless debugging")


def wireless_android_devices():
    result = []
    for line in _adb("devices", "-l").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[1] != "device":
            continue
        serial = fields[0]
        if ":" in serial or serial.endswith("._adb-tls-connect._tcp"):
            result.append(serial)
    return result


class PhoneMirror:
    def __init__(self, kind):
        if kind not in ("airplay", "android"):
            raise ValueError("Choose airplay or android")
        self.kind = kind
        self.pin = None
        self._process = self._log = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def running(self):
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self, audio=False):
        with self._lock:
            if self._closed:
                raise RuntimeError("Phone mirror has been closed")
            if self.running:
                raise RuntimeError("This phone mirror is already running")
            self.stop()
            environment = os.environ.copy()
            if self.kind == "airplay":
                path = executable("uxplay")
                self.pin = f"{secrets.randbelow(9000) + 1000}"
                args = [path, "-rc", "/dev/null", "-n", "iProjection", "-nh", "-pin", self.pin,
                        "-s", "1280x800@30", "-avdec", "-p", "35000"]
                if not audio:
                    args += ["-as", "0"]
            else:
                path = executable("scrcpy")
                devices = wireless_android_devices()
                if len(devices) != 1:
                    raise RuntimeError("Connect exactly one authorized wireless Android device; use Pair Android first")
                args = [path, f"--serial={devices[0]}", "--no-control", "--no-clipboard-autosync",
                        "--window-title=iProjection Android", "--max-size=1280", "--max-fps=30"]
                if not audio:
                    args.append("--no-audio")
                server = Path(path).resolve().parent.parent / "share" / "scrcpy" / "scrcpy-server"
                if server.is_file():
                    environment.setdefault("SCRCPY_SERVER_PATH", str(server))
            self._log = tempfile.TemporaryFile()
            try:
                self._process = subprocess.Popen(args, stdout=self._log, stderr=subprocess.STDOUT,
                                                 env=environment, start_new_session=True)
            except OSError:
                self.stop()
                raise
            return self.pin

    def finished(self):
        with self._lock:
            if self._process is None or self.running:
                return None
            result = self._process.returncode
            self._log.seek(0, os.SEEK_END)
            self._log.seek(max(0, self._log.tell() - 2048))
            detail = self._log.read().decode("utf-8", errors="replace").strip()
            if self.pin:
                detail = detail.replace(self.pin, "[PIN]")
            self.stop()
            return result, detail

    def stop(self):
        with self._lock:
            if self._process is not None:
                if self.running:
                    try:
                        os.killpg(self._process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        self._process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(self._process.pid, signal.SIGKILL)
                        self._process.wait(timeout=3)
                self._process = None
            if self._log is not None:
                self._log.close()
                self._log = None
            self.pin = None

    def close(self):
        with self._lock:
            self._closed = True
            self.stop()
