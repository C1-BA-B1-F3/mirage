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

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def _ws():
    mem = RAMVFS()
    ws = Workspace(
        {"/data": (mem, MountMode.WRITE)},
        mode=MountMode.WRITE,
    )
    return ws, mem


def _run_raw(ws, cmd, cwd="/", stdin=None):
    ws._cwd = cwd
    io = asyncio.run(ws.shell(cmd, stdin=stdin))
    return io.stdout, io


def _bytes(stdout):
    if isinstance(stdout, bytes):
        return stdout
    return b"".join(asyncio.run(_collect(stdout)))


async def _collect(ait):
    return [chunk async for chunk in ait]


def test_join_basic():
    ws, _ = _ws()
    _run_raw(ws, "tee /data/a.txt", stdin=b"1 Alice\n2 Bob\n")
    _run_raw(ws, "tee /data/b.txt", stdin=b"1 NY\n2 LA\n")
    stdout, io = _run_raw(ws, "join /data/a.txt /data/b.txt")
    out = _bytes(stdout).decode()
    assert "1 Alice NY" in out
    assert "2 Bob LA" in out


def test_join_reads_a_dash_operand_across_mounts():
    # From / the dash sits on the root mount, so the line relays.
    ws, _ = _ws()
    _run_raw(ws, "tee /data/f.txt", stdin=b"alice 30\nbob 25\n")
    stdout, io = _run_raw(ws, "join - /data/f.txt", stdin=b"alice 1\nbob 2\n")
    assert (_bytes(stdout), io.exit_code) == (b"alice 1 30\nbob 2 25\n", 0)


def test_join_refuses_two_dash_operands():
    ws, _ = _ws()
    stdout, io = _run_raw(ws, "join - -", stdin=b"a\n")
    assert io.exit_code == 1
    assert _bytes(io.stderr) == b"join: both files cannot be standard input\n"
