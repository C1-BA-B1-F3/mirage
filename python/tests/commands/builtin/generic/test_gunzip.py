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
import gzip

import pytest

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def _read_only_gunzip_mount() -> tuple[Workspace, RAMVFS]:
    vfs = RAMVFS()
    vfs._store.files["/f.txt.gz"] = gzip.compress(b"hello\n")
    return Workspace({"/ro/": (vfs, MountMode.READ)}), vfs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line", ["gunzip /ro/f.txt.gz", "gunzip -k /ro/f.txt.gz"]
)
async def test_a_read_only_mount_refuses_gunzip_at_the_write(line: str):
    ws, vfs = _read_only_gunzip_mount()
    before = dict(vfs._store.files)
    result = await ws.shell(line)
    assert result.exit_code == 1
    assert result.stderr == b"\ngzip: /ro/f.txt: Read-only file system\n"
    assert vfs._store.files == before


@pytest.mark.asyncio
async def test_a_dash_goes_to_stdout_while_files_decompress_in_place():
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    await ws.shell("tee /data/b.txt > /dev/null", stdin=b"file\n")
    r = await ws.shell(
        "cd /data && gzip b.txt && gunzip - b.txt.gz; ls; cat b.txt",
        stdin=gzip.compress(b"hi\n"),
    )
    assert await r.materialize_stdout() == b"hi\nb.txt\nfile\n"


@pytest.mark.asyncio
async def test_a_plain_file_is_reported_and_left_in_place():
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    await ws.shell("tee /data/b.txt > /dev/null", stdin=b"file\n")
    await ws.shell("tee /data/p.gz > /dev/null", stdin=b"plain\n")
    r = await ws.shell("cd /data && gzip b.txt && gunzip p.gz b.txt.gz; ls")
    assert await r.materialize_stdout() == b"b.txt\np.gz\n"
    assert (
        await r.materialize_stderr() == b"\ngzip: p.gz: not in gzip format\n"
    )


# gzip -n of "hello\n" with its CRC-32 and length trailer zeroed.
DAMAGED = gzip.compress(b"hello\n", mtime=0)[:-8] + b"\0" * 8


@pytest.mark.asyncio
async def test_a_damaged_trailer_keeps_the_inflated_bytes():
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    await ws.shell("tee /data/bad.gz > /dev/null", stdin=DAMAGED)
    await ws.shell("tee /data/ok.gz > /dev/null", stdin=gzip.compress(b"x\n"))
    r = await ws.shell("gunzip -c /data/bad.gz /data/ok.gz")
    assert r.exit_code == 1
    assert await r.materialize_stdout() == b"hello\n"
    assert await r.materialize_stderr() == (
        b"\ngzip: /data/bad.gz: invalid compressed data--crc error\n"
        b"\ngzip: /data/bad.gz: invalid compressed data--length error\n"
    )
    r = await ws.shell("gunzip -t /data/bad.gz /data/ok.gz; ls /data")
    assert await r.materialize_stdout() == b"bad.gz\nok.gz\n"


async def _linked(line: str) -> tuple[Workspace, str, str, int]:
    """Run ``line`` in /data beside t.gz and a link tl.gz naming it, with a
    read-only /ro holding f.gz, as gzip 1.13 was pinned."""
    ro = RAMVFS()
    ro._store.files["/f.gz"] = gzip.compress(b"ro\n")
    ws = Workspace(
        {
            "/data": (RAMVFS(), MountMode.WRITE),
            "/ro": (ro, MountMode.READ),
        },
        mode=MountMode.WRITE,
    )
    await ws.shell(
        "tee /data/t.gz > /dev/null", stdin=gzip.compress(b"hello\n")
    )
    await ws.shell("mkdir /data/dir && cd /data && ln -s t.gz tl.gz")
    r = await ws.shell(f"cd /data && {line}")
    return (
        ws,
        (await r.materialize_stdout()).decode(),
        (await r.materialize_stderr()).decode(),
        r.exit_code,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,err",
    [
        ("gunzip tl.gz", "gzip: tl.gz: Too many levels of symbolic links\n"),
        (
            "gunzip -k -q tl.gz",
            "gzip: tl.gz: Too many levels of symbolic links\n",
        ),
        ("gzip -d tl.gz", "gzip: tl.gz: Too many levels of symbolic links\n"),
        (
            "ln -s nowhere d.gz && gunzip d.gz",
            "gzip: d.gz: Too many levels of symbolic links\n",
        ),
        (
            "ln -s dir dl && gunzip dl",
            "gzip: dl: Too many levels of symbolic links\n",
        ),
        (
            "ln -s t.gz x.gz && gunzip x",
            "gzip: x.gz: Too many levels of symbolic links\n",
        ),
    ],
)
async def test_in_place_refuses_a_link_as_o_nofollow_does(line: str, err: str):
    ws, out, stderr, code = await _linked(line)
    assert (stderr, code) == (err, 1)
    listing = await ws.shell("ls /data")
    assert "t.gz" in (await listing.materialize_stdout()).decode()


@pytest.mark.asyncio
async def test_f_writes_beside_a_link_into_a_read_only_mount():
    ws, _, stderr, code = await _linked("ln -s /ro/f.gz rl.gz && gunzip -f rl")
    assert (stderr, code) == ("", 0)
    r = await ws.shell("cat /data/rl && ls /ro")
    assert await r.materialize_stdout() == b"ro\nf.gz\n"


@pytest.mark.asyncio
async def test_a_link_standing_at_the_output_name_is_an_output_already_there():
    ws, _, stderr, code = await _linked("ln -s dir t && gunzip t.gz")
    assert (stderr, code) == ("gzip: t already exists;\tnot overwritten\n", 2)
    ws, _, stderr, code = await _linked("ln -s dir t && gunzip -f t.gz")
    r = await ws.shell("cd /data && ls -F && cat t")
    assert (code, await r.materialize_stdout()) == (
        0,
        b"dir/\nt\ntl.gz@\nhello\n",
    )


@pytest.mark.asyncio
async def test_a_link_an_earlier_operand_removed_is_missing_at_its_turn():
    ws, _, stderr, code = await _linked("gunzip -f tl.gz tl.gz")
    assert (stderr, code) == ("gzip: tl.gz: No such file or directory\n", 1)
    r = await ws.shell("cd /data && ls")
    assert await r.materialize_stdout() == b"dir\nt.gz\ntl\n"
