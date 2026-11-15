import signal
import subprocess
from types import SimpleNamespace

import pytest

from linux_iprojection import phone_mirror as phones


@pytest.mark.parametrize("address", ["--option", "example.com:1234", "192.168.1.2:0", "192.168.1.2:65536"])
def test_pairing_rejects_invalid_endpoints_without_network(mocker, address):
    adb = mocker.patch.object(phones, "_adb")
    with pytest.raises(ValueError, match="IPv4 address and port"):
        phones.pair_android(address, "123456", "192.168.1.2:37123")
    adb.assert_not_called()


@pytest.mark.parametrize("code", ["", "1234", "１２３４５６", "12345x"])
def test_pairing_rejects_invalid_codes(mocker, code):
    adb = mocker.patch.object(phones, "_adb")
    with pytest.raises(ValueError, match="six-digit"):
        phones.pair_android("192.168.1.2:37000", code, "192.168.1.2:37123")
    adb.assert_not_called()


def test_pair_then_connect_and_verify_authorization(mocker):
    adb = mocker.patch.object(phones, "_adb", side_effect=["Successfully paired to phone", "connected", "device"])
    phones.pair_android("192.168.1.2:37000", "123456", "192.168.1.2:37123")
    assert adb.call_args_list == [
        mocker.call("pair", "192.168.1.2:37000", input="123456\n"),
        mocker.call("connect", "192.168.1.2:37123"),
        mocker.call("-s", "192.168.1.2:37123", "get-state"),
    ]


def test_pairing_failure_does_not_connect(mocker):
    adb = mocker.patch.object(phones, "_adb", return_value="Failed to pair")
    with pytest.raises(RuntimeError, match="did not confirm pairing"):
        phones.pair_android("192.168.1.2:37000", "123456", "192.168.1.2:37123")
    assert adb.call_count == 1


def test_adb_errors_do_not_expose_pairing_code(mocker):
    mocker.patch.object(phones, "executable", return_value="/usr/bin/adb")
    run = mocker.patch.object(phones.subprocess, "run", side_effect=subprocess.CalledProcessError(
        1, ["adb", "pair", "192.168.1.2:37000"], stderr="Rejected 123456",
    ))
    with pytest.raises(RuntimeError, match=r"Rejected \[code\]"):
        phones._adb("pair", "192.168.1.2:37000", input="123456\n")
    assert "123456" not in run.call_args.args[0]


def test_wireless_list_excludes_usb_and_unauthorized_devices(mocker):
    mocker.patch.object(phones, "_adb", return_value=(
        "List of devices attached\n"
        "192.168.1.2:37123 device product:test\n"
        "192.168.1.3:37123 unauthorized\n"
        "ABC123 device usb:1-2\n"
        "adb-XYZ._adb-tls-connect._tcp device product:test\n"
    ))
    assert phones.wireless_android_devices() == ["192.168.1.2:37123", "adb-XYZ._adb-tls-connect._tcp"]


@pytest.fixture
def process(mocker):
    mocker.patch.object(phones, "executable", side_effect=lambda name: f"/usr/bin/{name}")
    mocker.patch.object(phones.secrets, "randbelow", return_value=123)
    process = mocker.Mock(pid=12345)
    process.poll.return_value = None
    popen = mocker.patch.object(phones.subprocess, "Popen", return_value=process)
    kill = mocker.patch.object(phones.os, "killpg")
    return SimpleNamespace(child=process, popen=popen, kill=kill)


def test_airplay_is_explicit_pin_protected_and_owned(process):
    mirror = phones.PhoneMirror("airplay")
    process.popen.assert_not_called()
    assert mirror.start() == "1123"
    args = process.popen.call_args.args[0]
    assert args[args.index("-pin") + 1] == "1123"
    assert args[args.index("-rc") + 1] == "/dev/null"
    assert args[args.index("-p") + 1] == "35000"
    assert args[-2:] == ["-as", "0"]
    assert process.popen.call_args.kwargs["start_new_session"] is True
    with pytest.raises(RuntimeError, match="already running"):
        mirror.start()
    log = process.popen.call_args.kwargs["stdout"]
    mirror.close()
    process.kill.assert_called_once_with(12345, signal.SIGTERM)
    assert log.closed and not mirror.running
    with pytest.raises(RuntimeError, match="has been closed"):
        mirror.start()


@pytest.mark.parametrize("audio", [False, True])
def test_android_mirrors_only_authorized_device_without_input_control(mocker, process, audio):
    mocker.patch.object(phones, "wireless_android_devices", return_value=["192.168.1.2:37123"])
    mirror = phones.PhoneMirror("android")
    mirror.start(audio=audio)
    args = process.popen.call_args.args[0]
    assert "--serial=192.168.1.2:37123" in args
    assert "--no-control" in args and "--no-clipboard-autosync" in args
    assert ("--no-audio" in args) == (not audio)
    mirror.stop()


@pytest.mark.parametrize("devices", [[], ["192.168.1.2:3", "192.168.1.4:5"]])
def test_android_requires_an_unambiguous_authorized_wireless_device(mocker, process, devices):
    mocker.patch.object(phones, "wireless_android_devices", return_value=devices)
    with pytest.raises(RuntimeError, match="exactly one authorized"):
        phones.PhoneMirror("android").start()
    process.popen.assert_not_called()


def test_failed_receiver_reports_bounded_redacted_diagnostics(process):
    mirror = phones.PhoneMirror("airplay")
    mirror.start()
    process.popen.call_args.kwargs["stdout"].write(b"PIN 1123; bind failed")
    process.child.poll.return_value = 1
    process.child.returncode = 1
    assert mirror.finished() == (1, "PIN [PIN]; bind failed")
    assert mirror.finished() is None
    process.kill.assert_not_called()


def test_stop_escalates_only_its_own_process_group(process):
    mirror = phones.PhoneMirror("airplay")
    mirror.start()
    process.child.wait.side_effect = [subprocess.TimeoutExpired("uxplay", 3), 0]
    mirror.stop()
    assert [call.args for call in process.kill.call_args_list] == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]


def test_spawn_failure_closes_diagnostics_and_clears_pin(process):
    process.popen.side_effect = OSError("spawn failed")
    mirror = phones.PhoneMirror("airplay")
    with pytest.raises(OSError, match="spawn failed"):
        mirror.start()
    assert mirror.pin is None and mirror._log is None and not mirror.running
