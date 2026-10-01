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
import gzip
import zlib

import pytest

from mirage.commands.builtin.generic.gzip import extract_level
from mirage.commands.builtin.generic.gzip import gzip as compress_inputs
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.types import MountMode, PathSpec
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace
from mirage.workspace.executor.command.flags import parse_flags


def _level(argv: list[str]) -> int:
    parsed = parse_flags(argv, SPECS["gzip"], "gzip", "/")
    return extract_level(FlagView(parsed.flag_kwargs, spec=SPECS["gzip"]))


@pytest.mark.parametrize("digit", list(range(1, 10)))
def test_every_digit_flag_selects_its_level(digit: int):
    """-1..-9 each select their own level, including -1.

    ``-1`` is the one digit the parser disambiguates (``args_1``), so a
    bag read by the bare digit missed it and silently compressed at
    zlib's default.
    """
    assert _level([f"-{digit}"]) == digit


def test_no_digit_flag_keeps_the_zlib_default():
    assert _level([]) == zlib.Z_DEFAULT_COMPRESSION


def test_the_highest_digit_wins():
    """GNU takes the last level flag; the parser leaves all of them set."""
    assert _level(["-1", "-9"]) == 9


def _read_only_gzip_mount() -> tuple[Workspace, RAMVFS]:
    vfs = RAMVFS()
    vfs._store.files["/f.txt"] = b"hello\n"
    vfs._store.files["/f.txt.gz"] = gzip.compress(b"hello\n")
    vfs._store.files["/g.txt"] = b"fresh\n"
    return Workspace({"/ro/": (vfs, MountMode.READ)}), vfs


@pytest.mark.parametrize(
    "line,stdout",
    [
        ("cd /ro && printf 'x\\n' | gzip | gunzip", b"x\n"),
        ("gzip -c /ro/f.txt | gunzip", b"hello\n"),
        ("gzip -dc /ro/f.txt.gz", b"hello\n"),
        ("cd /ro && printf 'x\\n' | gzip - | gunzip -", b"x\n"),
    ],
)
def test_a_read_only_mount_runs_gzip_where_it_writes_nothing(
    line: str, stdout: bytes
):
    ws, vfs = _read_only_gzip_mount()
    before = dict(vfs._store.files)
    result = asyncio.run(ws.shell(line))
    assert (result.exit_code, result.stdout) == (0, stdout)
    assert vfs._store.files == before


_EXISTS = "gzip: /ro/f.txt.gz already exists;\tnot overwritten\n"


@pytest.mark.parametrize(
    "line,code,stderr",
    [
        ("gzip /ro/f.txt", 2, _EXISTS),
        ("gzip -k /ro/f.txt", 2, _EXISTS),
        (
            "gzip -f /ro/f.txt",
            1,
            "gzip: /ro/f.txt.gz: Read-only file system\n",
        ),
        ("gzip /ro/g.txt", 1, "\ngzip: /ro/g.txt.gz: Read-only file system\n"),
        (
            "gzip /ro/f.txt /ro/g.txt",
            1,
            _EXISTS + "\ngzip: /ro/g.txt.gz: Read-only file system\n",
        ),
        (
            "gzip -d /ro/f.txt.gz",
            2,
            "gzip: /ro/f.txt already exists;\tnot overwritten\n",
        ),
        (
            "gzip -df /ro/f.txt.gz",
            1,
            "gzip: /ro/f.txt: Read-only file system\n",
        ),
    ],
)
def test_a_read_only_mount_refuses_gzip_at_the_write(
    line: str, code: int, stderr: str
):
    # Nothing refuses the command before it runs: the write of the
    # replacement file is what the mount refuses, in gzip's own voice,
    # and the operand it would have replaced is left in place. An output
    # already there is left alone without -f (a warning); -f's refused
    # replace goes on to the next operand, and an output that cannot be
    # created ends the run with write_error's leading newline. Pinned
    # against gzip 1.13 on a read-only tmpfs.
    ws, vfs = _read_only_gzip_mount()
    before = dict(vfs._store.files)
    result = asyncio.run(ws.shell(line))
    assert (result.exit_code, result.stderr) == (code, stderr.encode())
    assert vfs._store.files == before


@pytest.mark.asyncio
async def test_a_dash_goes_to_stdout_while_files_compress_in_place():
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    await ws.shell("tee /data/a.txt > /dev/null", stdin=b"file\n")
    r = await ws.shell(
        "cd /data && gzip - a.txt | gzip -dc; ls", stdin=b"hi\n"
    )
    assert await r.materialize_stdout() == b"hi\na.txt.gz\n"


async def _with_link(line: str) -> tuple[Workspace, str, int]:
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    await ws.shell("cd /data && printf 'hello\\n' > a.txt && ln -s a.txt al")
    r = await ws.shell(f"cd /data && {line}")
    return ws, (await r.materialize_stderr()).decode(), r.exit_code


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["gzip al", "gzip -k al", "gzip -q al"])
async def test_compressing_in_place_refuses_a_link(line: str):
    ws, stderr, code = await _with_link(line)
    assert (stderr, code) == (
        "gzip: al: Too many levels of symbolic links\n",
        1,
    )
    r = await ws.shell("cd /data && ls -F")
    assert await r.materialize_stdout() == b"a.txt\nal@\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,listing",
    [
        ("gzip -f al", b"a.txt\nal.gz\n"),
        ("gzip -kf al", b"a.txt\nal@\nal.gz\n"),
    ],
)
async def test_f_compresses_beside_the_link(line: str, listing: bytes):
    ws, stderr, code = await _with_link(line)
    r = await ws.shell("cd /data && ls -F && gunzip -c al.gz")
    assert (stderr, code) == ("", 0)
    assert await r.materialize_stdout() == listing + b"hello\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("skipped", [False, True])
async def test_compression_skips_suffixed_streams_and_reports_late_errors(
    skipped,
):
    reads = []
    writes = {}
    removed = []
    name = "/bad.gz" if skipped else "/bad"

    async def read(path):
        reads.append(path.virtual)
        yield b"hello\n"
        if path.virtual == name:
            reads.append("continued")
            raise PermissionError(path.virtual)

    async def write(path, data):
        writes[path.virtual] = data

    async def unlink(path):
        removed.append(path.virtual)

    _, io = await compress_inputs(
        [PathSpec.from_str_path(name), PathSpec.from_str_path("/good")],
        read_bytes=read,
        write_bytes=write,
        unlink=unlink,
    )
    assert io.exit_code == (0 if skipped else 1)
    assert io.stderr == (
        b"gzip: /bad.gz already has .gz suffix -- unchanged\n"
        if skipped
        else b"\ngzip: /bad: Permission denied\n"
    )
    assert reads == ([name, "/good"] if skipped else [name, "continued"])
    assert removed == (["/good"] if skipped else [])
    assert set(writes) == ({"/good.gz"} if skipped else set())
    if skipped:
        assert gzip.decompress(writes["/good.gz"]) == b"hello\n"
