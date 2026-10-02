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
async def test_grep_recursive_no_operand_searches_cwd(workspace):
    # GNU: `grep -r pat` with no path operand searches the cwd and
    # prints bare relative names (a.txt:hit, not ./a.txt:hit).
    await workspace.vfs.mkdir("/sub")
    await workspace.vfs.write("/a.txt", b"hello\n")
    await workspace.vfs.write("/sub/b.txt", b"hello\n")

    io = await workspace.shell("grep -r hello", cwd="/")
    assert io.exit_code == 0
    assert (io.stdout or b"") == b"a.txt:hello\nsub/b.txt:hello\n"


@pytest.mark.asyncio
async def test_grep_recursive_no_operand_ignores_stdin(workspace):
    # GNU ignores stdin whenever -r has to invent the cwd operand.
    await workspace.vfs.write("/a.txt", b"hello\n")

    io = await workspace.shell(
        "grep -r hello", cwd="/", stdin=b"hello from stdin\n"
    )
    assert io.exit_code == 0
    assert (io.stdout or b"") == b"a.txt:hello\n"


@pytest.mark.asyncio
async def test_grep_recursive_no_operand_no_match_exits_one(workspace):
    await workspace.vfs.write("/a.txt", b"hello\n")

    io = await workspace.shell("grep -r zzz", cwd="/")
    assert io.exit_code == 1
    assert (io.stdout or b"") == b""
    assert not io.stderr
