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

import pytest

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def _ws() -> Workspace:
    return Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                     mode=MountMode.WRITE)


@pytest.mark.asyncio
async def test_rm_f_of_the_empty_name_removes_nothing():
    # rm -f silences the empty name's ENOENT, and the bookkeeping after a
    # clean rm used to purge the node table under its `virtual`, the
    # working directory, taking every link there with it.
    ws = _ws()
    await ws.shell("mkdir -p /data/d; echo x > /data/d/f; ln -s f /data/d/l")
    r = await ws.shell("cd /data/d && rm -rf ''")
    assert r.exit_code == 0
    assert ws.namespace.is_link("/data/d/l")
    assert (await ws.shell("cat /data/d/f")).stdout == b"x\n"


@pytest.mark.asyncio
async def test_a_loop_fails_its_operand_not_the_line():
    ws = _ws()
    await ws.shell("echo a > /data/a.txt; echo b > /data/b.txt; "
                   "ln -s /data/l2 /data/l1; ln -s /data/l1 /data/l2")
    r = await ws.shell("cat /data/a.txt /data/l1 /data/b.txt")
    assert r.exit_code == 1
    assert r.stdout == b"a\nb\n"
    assert r.stderr == (b"cat: /data/l1: Too many levels of symbolic "
                        b"links\n")
