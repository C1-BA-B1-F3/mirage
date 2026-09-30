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
import errno

import pytest

from mirage import MountMode, Workspace
from mirage.commands.errors import CommandTimeoutError
from mirage.types import Limit
from mirage.vfs.ram import RAMVFS


async def _slow_op(accessor, scope, *args, **kwargs):
    await asyncio.sleep(5)
    return None


async def _slowish_op(accessor, scope, *args, **kwargs):
    await asyncio.sleep(0.2)
    return "ok"


async def _ws_mount():
    ws = Workspace({"/data": RAMVFS()}, mode=MountMode.WRITE)
    await ws.shell("echo hi > /data/f.txt")
    mount = next(m for m in ws._registry._mounts if m.prefix == "/data/")
    return mount


@pytest.mark.asyncio
async def test_vfs_op_honors_per_mount_timeout(monkeypatch):
    mount = await _ws_mount()
    mount.command_limits["stat"] = Limit(timeout_seconds=0.05)
    monkeypatch.setattr(mount._ops[("stat", None)], "fn", _slow_op)
    with pytest.raises(CommandTimeoutError):
        await mount.execute_op("stat", "/data/f.txt")


@pytest.mark.asyncio
async def test_vfs_op_unconfigured_is_not_timed(monkeypatch):
    mount = await _ws_mount()
    monkeypatch.setattr(mount._ops[("stat", None)], "fn", _slowish_op)
    result = await mount.execute_op("stat", "/data/f.txt")
    assert result == "ok"


def _slow_stream(accessor, scope, *args, **kwargs):

    async def body():
        await asyncio.sleep(5)
        yield b"late"

    return body()


@pytest.mark.asyncio
async def test_a_streamed_read_holds_each_pull_to_the_op_timeout(monkeypatch):
    mount = await _ws_mount()
    mount.command_limits["read"] = Limit(timeout_seconds=0.05)
    monkeypatch.setattr(mount._ops[("read", None)], "stream", _slow_stream)
    stream = await asyncio.wait_for(
        mount.execute_op("read", "/data/f.txt", stream=True), 1)
    with pytest.raises(CommandTimeoutError):
        await anext(stream)
    await asyncio.wait_for(mount.activity.wait(), 1)


async def _etimedout_op(accessor, scope, *args, **kwargs):
    await asyncio.sleep(0.01)
    raise TimeoutError(errno.ETIMEDOUT, "backend timed out")


def _etimedout_stream(accessor, scope, *args, **kwargs):

    async def body():
        yield b"first"
        await asyncio.sleep(0.01)
        raise TimeoutError(errno.ETIMEDOUT, "backend timed out")

    return body()


@pytest.mark.asyncio
async def test_a_backend_etimedout_under_the_op_timeout_keeps_its_errno(
        monkeypatch):
    mount = await _ws_mount()
    mount.command_limits["stat"] = Limit(timeout_seconds=5)
    monkeypatch.setattr(mount._ops[("stat", None)], "fn", _etimedout_op)
    with pytest.raises(TimeoutError) as exc:
        await mount.execute_op("stat", "/data/f.txt")
    assert exc.value.errno == errno.ETIMEDOUT
    assert not isinstance(exc.value, CommandTimeoutError)


@pytest.mark.asyncio
async def test_a_streamed_pull_keeps_a_backend_etimedout_errno(monkeypatch):
    mount = await _ws_mount()
    mount.command_limits["read"] = Limit(timeout_seconds=5)
    monkeypatch.setattr(mount._ops[("read", None)], "stream",
                        _etimedout_stream)
    stream = await mount.execute_op("read", "/data/f.txt", stream=True)
    assert await anext(stream) == b"first"
    with pytest.raises(TimeoutError) as exc:
        await anext(stream)
    assert exc.value.errno == errno.ETIMEDOUT
    assert not isinstance(exc.value, CommandTimeoutError)
    await asyncio.wait_for(mount.activity.wait(), 1)
