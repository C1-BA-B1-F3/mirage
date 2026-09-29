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

from mirage.commands.builtin.generic.diff import diff
from mirage.commands.errors import UsageError
from mirage.io.stream import materialize
from mirage.types import FileStat, FileType, PathSpec


def _operand(raw: str, virtual: str) -> PathSpec:
    return PathSpec(virtual=virtual,
                    directory=virtual,
                    vfs_path=virtual.removeprefix("/d/"),
                    raw_path=raw)


DASH = _operand("-", "/d/-")
DEV_STDIN = PathSpec.from_str_path("/dev/stdin", "")
FILE = _operand("a.txt", "/d/a.txt")
SUB = _operand("sub", "/d/sub")
SUB2 = _operand("sub2", "/d/sub2")
FILES = {
    "/d/a.txt": b"hello\n",
    "/d/sub/x": b"1\n",
    "/d/sub2/x": b"2\n",
    "/d/sub2/y": b"3\n"
}
DIRS = {"/d/sub": ["x"], "/d/sub2": ["x", "y"]}


async def _read(path: PathSpec) -> bytes:
    return FILES[path.virtual]


async def _readdir(path: PathSpec) -> list[str]:
    return DIRS[path.virtual]


async def _stat(path: PathSpec) -> FileStat:
    kind = FileType.DIRECTORY if path.virtual in DIRS else FileType.FILE
    return FileStat(name=path.virtual.rsplit("/", 1)[-1], type=kind)


async def _run(paths: list[PathSpec], stdin: bytes | None = None, **flags):
    out, io = await diff(paths,
                         read_bytes=_read,
                         readdir_fn=_readdir,
                         stat_fn=_stat,
                         stdin=stdin,
                         **flags)
    body = b"" if out is None else await materialize(out)
    return body.decode(), (io.stderr or b"").decode(), io.exit_code


@pytest.mark.asyncio
async def test_a_dash_operand_reads_stdin_and_is_named_dash():
    assert await _run([DASH, FILE], b"x\n",
                      q=True) == ("Files - and a.txt differ\n", "", 1)


@pytest.mark.asyncio
async def test_unified_headers_name_the_operands_as_typed():
    out, _, code = await _run([FILE, DEV_STDIN], b"x\n", u=True)
    assert out.startswith("--- a.txt\n+++ /dev/stdin\n")
    assert code == 1


@pytest.mark.asyncio
async def test_two_stdin_operands_are_one_file():

    async def unread(path: PathSpec) -> bytes:
        raise AssertionError(f"read {path.virtual}")

    out, io = await diff([DASH, DEV_STDIN],
                         read_bytes=unread,
                         readdir_fn=_readdir,
                         stat_fn=_stat,
                         stdin=b"abc")
    assert (out, io.exit_code) == (None, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("paths", [[DASH, SUB], [SUB, DASH]])
async def test_a_dash_against_a_directory_is_refused(paths):
    assert await _run(
        paths, b"x\n") == ("", "diff: cannot compare '-' to a directory\n", 2)


@pytest.mark.asyncio
async def test_a_lone_operand_is_gnus_missing_operand_usage_error():
    with pytest.raises(UsageError) as exc:
        await _run([FILE])
    assert str(exc.value) == ("diff: missing operand after 'a.txt'\n"
                              "diff: Try 'diff --help' for more information.")
    assert exc.value.exit_code == 2


@pytest.mark.asyncio
async def test_recursive_output_names_children_under_the_typed_operands():
    assert await _run([SUB, SUB2], r=True) == (
        "diff -r sub/x sub2/x\n1c1\n< 1\n---\n> 2\nOnly in sub2: y\n", "", 1)
