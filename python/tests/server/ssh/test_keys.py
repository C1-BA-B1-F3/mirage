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
import os
import stat
import subprocess
import sys
from pathlib import Path

import asyncssh
import pytest

from mirage.server.ssh.keys import HOST_KEY_ALGORITHM, load_host_key
from mirage.workspace.record.disk import DiskRecordClient


def _public(key: asyncssh.SSHKey) -> bytes:
    return key.export_public_key()


@pytest.mark.asyncio
async def test_first_load_mints_an_owner_only_key(tmp_path):
    path = tmp_path / "ssh" / "host_key"
    key = await load_host_key(path)
    assert key.get_algorithm() == HOST_KEY_ALGORITHM
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_later_loads_keep_the_same_key(tmp_path):
    path = tmp_path / "host_key"
    first = await load_host_key(path)
    assert _public(await load_host_key(path)) == _public(first)


@pytest.mark.asyncio
async def test_an_existing_key_is_read_not_replaced(tmp_path):
    path = tmp_path / "host_key"
    mine = asyncssh.generate_private_key("ssh-ed25519")
    path.write_bytes(mine.export_private_key())
    assert _public(await load_host_key(path)) == _public(mine)


@pytest.mark.asyncio
async def test_racing_loads_agree_on_one_key_without_hard_links(
    tmp_path, monkeypatch
):
    path = tmp_path / "host_key"

    def no_links(src, dst):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    keys = await asyncio.gather(*(load_host_key(path) for _ in range(8)))
    assert len({_public(key) for key in keys}) == 1
    assert _public(asyncssh.read_private_key(str(path))) == _public(keys[0])
    assert [p.name for p in tmp_path.iterdir()] == ["host_key"]


@pytest.mark.asyncio
async def test_a_start_waiting_on_the_lock_reads_the_winner(tmp_path):
    path = tmp_path / "host_key"
    records = DiskRecordClient(str(tmp_path), "")
    lock = await records.lock(path.name)
    loading = asyncio.ensure_future(load_host_key(path))
    await asyncio.sleep(0.05)
    winner = asyncssh.generate_private_key("ssh-ed25519")
    path.write_bytes(winner.export_private_key())
    await records.unlock(path.name, lock)
    assert _public(await loading) == _public(winner)


@pytest.mark.asyncio
async def test_a_lock_left_by_a_killed_start_does_not_hold_up_the_next(
    tmp_path,
):
    path = tmp_path / "host_key"
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    lock = DiskRecordClient(str(tmp_path), "").path(path.name) + ".lock"
    Path(lock).write_text(str(child.pid))
    key = await asyncio.wait_for(load_host_key(path), 2)
    assert _public(asyncssh.read_private_key(str(path))) == _public(key)
    assert [p.name for p in tmp_path.iterdir()] == ["host_key"]


@pytest.mark.asyncio
async def test_a_failed_write_leaves_no_key_file(tmp_path, monkeypatch):
    def disk_full(self, *args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(asyncssh.SSHKey, "export_private_key", disk_full)
    with pytest.raises(OSError):
        await load_host_key(tmp_path / "host_key")
    assert list(tmp_path.iterdir()) == []
