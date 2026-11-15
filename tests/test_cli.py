from types import SimpleNamespace

import pytest

from linux_iprojection import cli
from linux_iprojection.protocol import KeystoneAxis


@pytest.mark.asyncio
@pytest.mark.parametrize("axis,expected", [("h", KeystoneAxis.HORIZONTAL), ("v", KeystoneAxis.VERTICAL)])
async def test_keystone_cli_uses_wire_range_and_axis(mocker, axis, expected):
    backend = mocker.AsyncMock()
    backend.__aenter__.return_value = backend
    mocker.patch.object(cli, "ProjectorClient", return_value=backend)
    await cli._keystone(SimpleNamespace(axis=axis, value=192, ip="127.0.0.1"))
    backend.set_keystone.assert_awaited_once_with(expected, 192)


@pytest.mark.asyncio
async def test_cast_cli_passes_extended_display_choice(mocker):
    caster = mocker.Mock(user_cancelled=True)
    caster.start = mocker.AsyncMock(return_value=False)
    mocker.patch.object(cli, "EasyMPCaster", return_value=caster)
    args = SimpleNamespace(ip="127.0.0.1", switch_source=False, video_port=5004,
                           audio_port=5006, transport="easymp", quality="balanced", extend=True)
    with pytest.raises(SystemExit) as exit_info:
        await cli._cast(args)
    assert exit_info.value.code == 0
    assert caster.start.await_args.kwargs == {"virtual": True}
