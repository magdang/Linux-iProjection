"""Virtual outputs belong to one cast and never bypass portal selection."""

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from linux_iprojection import cast
from linux_iprojection.virtual_display import VirtualMonitor


def test_output_lifetime_and_idempotent_cleanup(mocker):
    run = mocker.patch("linux_iprojection.virtual_display.subprocess.run", return_value=SimpleNamespace(stdout="ok\n"))
    monitor = VirtualMonitor()
    name = monitor.create()
    assert name.startswith("iProjection-")
    with pytest.raises(cast.PortalError, match="already active"):
        monitor.create()
    monitor.close()
    monitor.close()
    assert [call.args[0] for call in run.call_args_list] == [
        ["hyprctl", "output", "create", "headless", name],
        ["hyprctl", "output", "remove", name],
    ]
    assert monitor.name is None


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("hyprctl", 5)])
def test_creation_failure_still_attempts_cleanup(mocker, failure):
    run = mocker.patch("linux_iprojection.virtual_display.subprocess.run", side_effect=[failure, SimpleNamespace(stdout="ok")])
    monitor = VirtualMonitor()
    with pytest.raises(cast.PortalError, match="Could not create"):
        monitor.create()
    assert run.call_args_list[1].args[0][-1] == run.call_args_list[0].args[0][-1]
    assert monitor.name is None


def test_failed_removal_can_be_retried(mocker):
    run = mocker.patch("linux_iprojection.virtual_display.subprocess.run", side_effect=[
        SimpleNamespace(stdout="ok"), OSError("busy"), SimpleNamespace(stdout="ok"),
    ])
    monitor = VirtualMonitor()
    name = monitor.create()
    monitor.close()
    assert monitor.name == name
    monitor.close()
    assert monitor.name is None
    assert run.call_count == 3


@pytest.fixture
def portal(mocker):
    callbacks, selected = [], []
    properties = {"AvailableSourceTypes": 7, "AvailableCursorModes": 1}
    stream = {"mapping_id": "iProjection-test", "source_type": 1}
    bus = mocker.Mock()
    bus.get_unique_name.return_value = ":1.42"
    mocker.patch.object(cast.Gio, "bus_get_sync", return_value=bus)
    proxy = mocker.Mock()
    proxy.get_cached_property.side_effect = lambda name: cast.GLib.Variant("u", properties[name])
    request = mocker.Mock()
    request.connect.side_effect = lambda signal, callback: callbacks.append(callback) or len(callbacks)
    mocker.patch.object(cast.Gio.DBusProxy, "new_sync", side_effect=lambda *args: proxy if args[5].endswith("ScreenCast") else request)

    def call(method, args, *_):
        result = {}
        if method == "CreateSession":
            result = {"session_handle": "/test/session"}
        elif method == "SelectSources":
            selected.append(args.unpack()[1])
        elif method == "Start":
            result = {"streams": [(42, stream)]}
        callbacks[-1](None, None, "Response", SimpleNamespace(unpack=lambda: (0, result)))

    proxy.call_sync.side_effect = call
    close = mocker.patch.object(cast, "_close_session")
    return SimpleNamespace(properties=properties, stream=stream, selected=selected, close=close, proxy=proxy)


@pytest.mark.asyncio
@pytest.mark.parametrize("virtual,name,available,expected", [
    (False, None, 1, 1), (True, None, 7, 4), (False, "iProjection-test", 7, 1),
])
async def test_portal_selects_only_supported_sources(portal, virtual, name, available, expected):
    portal.properties["AvailableSourceTypes"] = available
    assert await cast._request_portal_stream(virtual=virtual, monitor_name=name) == (42, "/test/session")
    assert portal.selected[0]["types"] == expected
    assert portal.selected[0]["cursor_mode"] == 1
    portal.close.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_virtual_mode_never_opens_picker(portal):
    portal.properties["AvailableSourceTypes"] = 3
    with pytest.raises(cast.PortalError, match="does not support"):
        await cast._request_portal_stream(virtual=True)
    portal.proxy.call_sync.assert_not_called()


@pytest.mark.asyncio
async def test_extend_rejects_an_existing_screen_and_closes_session(portal):
    portal.stream["mapping_id"] = "eDP-1"
    with pytest.raises(cast.PortalError, match="select iProjection-test"):
        await cast._request_portal_stream(monitor_name="iProjection-test")
    portal.close.assert_called_once_with("/test/session")


@pytest.mark.asyncio
async def test_cancelled_task_closes_created_portal_session(portal):
    original = portal.proxy.call_sync.side_effect

    def call(method, *args):
        if method == "SelectSources":
            raise asyncio.CancelledError
        return original(method, *args)

    portal.proxy.call_sync.side_effect = call
    with pytest.raises(asyncio.CancelledError):
        await cast._request_portal_stream(virtual=True)
    portal.close.assert_called_once_with("/test/session")


@pytest.mark.asyncio
@pytest.mark.parametrize("hyprland", [True, False])
async def test_native_extend_picker_cancellation_releases_output(mocker, monkeypatch, hyprland):
    from linux_iprojection.easymp_cast import EasyMPCaster

    if hyprland:
        monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test")
    else:
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monitor = mocker.patch("linux_iprojection.easymp_cast.VirtualMonitor").return_value
    monitor.create.return_value = "iProjection-test"
    picker = mocker.patch("linux_iprojection.easymp_cast._request_portal_stream", side_effect=cast.UserCancelledError)
    client = mocker.patch("linux_iprojection.easymp_cast.EasyMPClient")
    caster = EasyMPCaster()
    assert not await caster.start(cast.CastTarget("127.0.0.1"), virtual=True)
    assert caster.user_cancelled
    picker.assert_awaited_once_with(**({"monitor_name": "iProjection-test"} if hyprland else {"virtual": True}))
    assert monitor.create.call_count == int(hyprland)
    monitor.close.assert_called_once()
    client.assert_not_called()
