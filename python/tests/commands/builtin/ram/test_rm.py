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

from mirage import RAMVFS, MountMode, Workspace


@pytest.fixture
def workspace():
    return Workspace({"/": RAMVFS()}, mode=MountMode.WRITE)


@pytest.mark.asyncio
async def test_rm_v_terminates_verbose_output(workspace):
    await workspace.vfs.write("/a.txt", b"a")

    io = await workspace.shell("rm -v /a.txt")

    assert io.exit_code == 0
    assert io.stdout == b"removed '/a.txt'\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [MountMode.WRITE, MountMode.READ])
async def test_rm_without_operands_answers_like_gnu(mode):
    ws = Workspace({"/m/": (RAMVFS(), mode)})
    forced = await ws.shell("cd /m && rm -f")
    bare = await ws.shell("cd /m && rm")
    assert (forced.exit_code, forced.stdout, forced.stderr) == (0, b"", None)
    assert bare.exit_code == 1
    assert bare.stderr == (b"rm: missing operand\n"
                           b"Try 'rm --help' for more information.\n")
