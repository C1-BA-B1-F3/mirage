# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from mirage.accessor.ssh import SSHAccessor, _connect_kwargs
from mirage.core.ssh.config import SSHConfig


def test_connect_kwargs_overrides():
    cfg = SSHConfig(
        host="dev",
        hostname="10.0.0.1",
        port=2222,
        username="admin",
        identity_file="~/.ssh/custom.pem",
    )
    kw = _connect_kwargs(cfg)
    assert kw["host"] == "10.0.0.1"
    assert kw["port"] == 2222
    assert kw["username"] == "admin"


def test_connect_kwargs_defaults():
    kw = _connect_kwargs(SSHConfig(host="dev"))
    assert kw["host"] == "dev"
    assert "port" not in kw
    assert "username" not in kw
    assert kw["known_hosts"] is None
    assert kw["login_timeout"] == 30


def test_connect_kwargs_password_and_passphrase():
    cfg = SSHConfig(
        host="dev", password="pw", identity_file="~/k", passphrase="pp"
    )
    kw = _connect_kwargs(cfg)
    assert kw["password"] == "pw"
    assert kw["passphrase"] == "pp"


def test_connect_kwargs_passphrase_rides_the_identity_file():
    kw = _connect_kwargs(SSHConfig(host="dev", passphrase="pp"))
    assert "passphrase" not in kw
    assert "password" not in kw


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_ssh_owns_connections_during_initialization(monkeypatch, fail):
    entered, release = asyncio.Event(), asyncio.Event()
    client = Mock()

    async def start():
        entered.set()
        await release.wait()
        return client

    conn = Mock(
        start_sftp_client=AsyncMock(side_effect=start), wait_closed=AsyncMock()
    )
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr("mirage.accessor.ssh.asyncssh.connect", connect)
    accessor = SSHAccessor(SSHConfig(host="unused"))
    first = asyncio.create_task(accessor.sftp())
    await entered.wait()
    if fail:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert accessor._conn is None
    else:
        second = asyncio.create_task(accessor.sftp())
        release.set()
        assert await first is await second is client
    await asyncio.gather(accessor.close(), accessor.close())
    connect.assert_awaited_once()
    conn.close.assert_called_once()
    conn.wait_closed.assert_awaited_once()

