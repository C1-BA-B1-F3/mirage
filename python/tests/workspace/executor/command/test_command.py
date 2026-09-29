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


@pytest.mark.asyncio
async def test_the_empty_name_routes_nowhere():
    # Its `virtual` is the working directory, here the root mount, which
    # used to make the line span mounts it never names.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE)
    await ws.shell("echo a > /data/a.txt")
    r = await ws.shell("cd / && cat '' /data/a.txt")
    assert r.exit_code == 1
    assert r.stdout == b"a\n"
    assert r.stderr == b"cat: '': No such file or directory\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("line,err", [
    ("cmp -s", "cmp: missing operand after '-s'\n"),
    ("cmp -n 5 --", "cmp: missing operand after '--'\n"),
    ("diff -u", "diff: missing operand after '-u'\n"),
    ("cd /data && join a.txt -t ,", "join: missing operand after ','\n"),
])
async def test_a_handler_sees_the_words_the_line_spelled(line, err):
    # The words after the command name reach the handler as typed, which
    # is where GNU's `missing operand after '<word>'` reads its word.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE)
    await ws.shell("echo a > /data/a.txt")
    r = await ws.shell(line)
    assert (r.stderr or b"").decode().startswith(err)
