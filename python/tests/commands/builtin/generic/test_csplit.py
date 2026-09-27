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

from mirage.commands.builtin.generic.csplit import csplit
from mirage.types import MountMode, PathSpec
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


async def _no_read(path: PathSpec) -> bytes:
    raise AssertionError(f"read {path.virtual}: the input is stdin")


@pytest.mark.asyncio
@pytest.mark.parametrize("cwd,named", [
    ("/data", ["/data/xx00", "/data/xx01"]),
    ("/data/sub", ["/data/sub/xx00", "/data/sub/xx01"]),
])
async def test_stdin_outputs_are_named_in_the_working_directory(
        cwd: str, named: list[str]):
    # No operand and no -f to read a prefix from: `xx` in the working
    # directory names the outputs (GNU), and the writes keys stay
    # mount-relative.
    specs: list[PathSpec] = []

    async def write_bytes(path: PathSpec, data: bytes) -> None:
        specs.append(path)

    _, io = await csplit([], ["2"],
                         read_bytes=_no_read,
                         write_bytes=write_bytes,
                         stdin=b"a\nb\n",
                         mount_prefix="/data",
                         cwd=cwd)
    assert [p.virtual for p in specs] == named
    assert list(io.writes) == [name[len("/data"):] for name in named]


@pytest.mark.asyncio
async def test_a_prefix_path_is_named_on_the_executing_mount():
    specs: list[PathSpec] = []

    async def write_bytes(path: PathSpec, data: bytes) -> None:
        specs.append(path)

    prefix = PathSpec(virtual="/data/sub/cs",
                      directory="/data/sub/",
                      vfs_path="sub/cs")
    _, io = await csplit([], ["2"],
                         read_bytes=_no_read,
                         write_bytes=write_bytes,
                         stdin=b"a\nb\n",
                         prefix=prefix,
                         mount_prefix="/data")
    assert [p.virtual for p in specs] == ["/data/sub/cs00", "/data/sub/cs01"]
    assert list(io.writes) == ["/sub/cs00", "/sub/cs01"]


@pytest.mark.asyncio
async def test_a_dash_input_reads_stdin():
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE)
    r = await ws.shell("cd /data && csplit - 2 && cat xx01",
                       stdin=b"a\nb\nc\n")
    assert await r.materialize_stdout() == b"2\n4\nb\nc\n"


@pytest.mark.asyncio
async def test_dev_stdin_stays_a_path_so_no_piece_lands_in_dev():
    # /dev/stdin runs csplit on the /dev mount, where its pieces would be
    # written, so it is refused as a missing path rather than read.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE)
    r = await ws.shell("cd /data && csplit /dev/stdin 2", stdin=b"a\nb\nc\n")
    assert r.exit_code == 1
    assert await r.materialize_stderr() == (
        b"csplit: cannot open '/dev/stdin' for reading: "
        b"No such file or directory\n")
    listing = await ws.shell("ls /dev")
    assert b"xx00" not in (await listing.materialize_stdout() or b"")
