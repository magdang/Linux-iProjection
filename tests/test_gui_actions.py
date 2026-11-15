"""GUI synchronization must never turn status reads into projector writes."""

import asyncio
from types import SimpleNamespace

import pytest


def immediate_async(coro):
    def decorate(callback):
        callback(asyncio.run(coro), None)
    return decorate


def test_status_refresh_and_model_controls(mocker, monkeypatch, tmp_path):
    import gi
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio

    if Gdk.Display.get_default() is None:
        pytest.skip("GTK display unavailable")

    from linux_iprojection import app, config
    from linux_iprojection.client import UnifiedStatus
    from linux_iprojection.discovery import DiscoveredDevice

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path)
    for name in ("on_refresh", "_load_persisted_devices", "_start_polling", "_setup_tray_icon"):
        mocker.patch.object(app.MainWindow, name)
    monkeypatch.setattr(app, "_run_async", immediate_async)
    application = Adw.Application(application_id="dev.linux_iprojection.ControlTests", flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.register(None)
    window = app.MainWindow(application)
    status = UnifiedStatus(power="01", source="53", volume=48, sharpness=116,
                           brightness=125, contrast=125, color_mode="04", luminance="01",
                           hkeystone=143, vkeystone=192, freeze=False,
                           model="EB/PL-1945W/C745WN")
    backend = mocker.AsyncMock()
    backend.__aenter__.return_value = backend
    backend.get_status.return_value = status
    window._create_client = mocker.Mock(return_value=backend)
    queue_setting = mocker.patch.object(window, "_queue_setting")
    try:
        device = DiscoveredDevice("Test projector", "127.0.0.1", 3629, "scan", info={"model": status.model})
        window.on_device_selected(None, app.DeviceRow(device, lambda *_: None))
        queue_setting.assert_not_called()
        assert window._create_client.call_count == 1
        assert not window.bright_scale.get_sensitive(), "LAN standby is not an adjustable picture"
        assert window.sharp_scale.get_value() == 116
        assert window.hkey_scale.get_value() == 143
        assert window.vkey_scale.get_value() == 192
        assert window.hkey_scale.get_adjustment().get_upper() == 255
        assert not window.audio_switch.get_sensitive()
        assert window.display_mode_row.get_sensitive()
        assert not window.moderator_switch.is_sensitive()
        assert "A0" not in [source.value for source in window._source_choices]

        status.source = "30"
        status.aspect = "30"
        window._refresh_status()
        queue_setting.assert_not_called()
        assert window._create_client.call_count == 2
        assert window.bright_scale.get_sensitive()
        assert window.aspect_row.get_sensitive()
        assert window.source_dropdown.get_selected_item().get_string() == "Hdmi1"
    finally:
        window.destroy()
        application.quit()


def test_slider_debounce_only_sends_latest_value(mocker, monkeypatch):
    from linux_iprojection import app

    callbacks = []
    monkeypatch.setattr(app.GLib, "timeout_add", lambda delay, callback: callbacks.append(callback) or len(callbacks))
    remove = mocker.patch.object(app.GLib, "source_remove")
    monkeypatch.setattr(app, "_run_async", immediate_async)
    client = mocker.AsyncMock()
    client.__aenter__.return_value = client
    window = SimpleNamespace(current_device=SimpleNamespace(address="127.0.0.1", device_type="projector"),
                             _create_client=mocker.Mock(return_value=client))
    app.MainWindow._queue_setting(window, "set_brightness", 100)
    app.MainWindow._queue_setting(window, "set_brightness", 125)
    remove.assert_called_once_with(1)
    assert callbacks[-1]() is False
    client.set_brightness.assert_awaited_once_with(125)
    app.MainWindow._queue_setting(window, "set_brightness", 150)
    window.current_device = None
    callbacks[-1]()
    client.set_brightness.assert_awaited_once_with(125)
