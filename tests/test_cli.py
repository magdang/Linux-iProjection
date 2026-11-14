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
