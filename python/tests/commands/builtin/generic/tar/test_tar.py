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
import io
import tarfile

import pytest

from mirage.commands.builtin.generic.tar.constants import (
    MODE_CONFLICT,
    MULTIPLE_ARCHIVES,
)
from mirage.commands.builtin.generic.tar.tar import (
    parse_flags as tar_parse_flags,
)
from mirage.commands.builtin.generic.tar.tar import strip_count
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS, parse_command, parse_to_kwargs
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

CHILD_FAILED = (
    b"tar: Child returned status 1\n"
    b"tar: Error is not recoverable: exiting now\n"
)


def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


OK = gzip.compress(_tar({"d/a.txt": b"hello\n", "d/b.txt": b"bee\n"}), mtime=0)
# The same archive with its CRC-32 and length trailer zeroed.
DAMAGED = OK[:-8] + b"\0" * 8


async def _shell(line: str, seed: dict[str, bytes]):
    ws = Workspace(
        {"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.WRITE
    )
    for path, data in seed.items():
        await ws.shell(f"tee {path} > /dev/null", stdin=data)
    r = await ws.shell(line)
    return (
        r.exit_code,
        await r.materialize_stdout(),
        await r.materialize_stderr(),
    )


@pytest.mark.asyncio
async def test_a_non_gzip_archive_is_gzips_refusal_then_tars():
    # GNU tar 1.35 reads -z through a gzip -d child and dies when it
    # fails, after gzip's own line.
    r = await _shell("tar -tzf /data/c.tgz", {"/data/c.tgz": b"corrupted\n"})
    assert r == (2, b"", b"\ngzip: stdin: not in gzip format\n" + CHILD_FAILED)


@pytest.mark.asyncio
async def test_a_damaged_trailer_still_yields_every_member():
    seed = {"/data/bad.tgz": DAMAGED}
    reasons = (
        b"\ngzip: stdin: invalid compressed data--crc error\n"
        b"\ngzip: stdin: invalid compressed data--length error\n"
    )
    assert await _shell("tar -tzf /data/bad.tgz nomatch", seed) == (
        2,
        b"",
        reasons + CHILD_FAILED,
    )
    r = await _shell("tar -xzf /data/bad.tgz -C /data; cat /data/d/*", seed)
    assert r == (0, b"hello\nbee\n", reasons + CHILD_FAILED)


@pytest.mark.asyncio
async def test_the_gzip_magic_takes_the_same_road_without_z():
    r = await _shell("tar -tf /data/junk.tgz", {"/data/junk.tgz": OK + b"xy"})
    assert r == (
        2,
        b"d/a.txt\nd/b.txt\n",
        b"\ngzip: stdin: decompression OK, trailing garbage ignored\n"
        b"tar: Child returned status 2\n"
        b"tar: Error is not recoverable: exiting now\n",
    )


@pytest.mark.asyncio
async def test_a_member_cut_short_yields_nothing():
    r = await _shell("tar -tzf /data/cut.tgz", {"/data/cut.tgz": OK[:-40]})
    assert r == (
        2,
        b"",
        b"\ngzip: stdin: unexpected end of file\n" + CHILD_FAILED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [OK[:-8], OK[:-3], OK + OK[:2]])
@pytest.mark.parametrize("flags", ["-tzf", "-tf", "-xOzf"])
async def test_a_truncated_gzip_wrapper_keeps_complete_tar_members(
    data, flags
):
    out = b"hello\nbee\n" if flags == "-xOzf" else b"d/a.txt\nd/b.txt\n"
    r = await _shell(f"tar {flags} /data/cut.tgz", {"/data/cut.tgz": data})
    assert r == (
        2,
        out,
        b"\ngzip: stdin: unexpected end of file\n" + CHILD_FAILED,
    )


@pytest.mark.asyncio
async def test_a_truncated_gzip_trailer_still_extracts_to_disk():
    r = await _shell(
        "tar -xzf /data/cut.tgz -C /data; cat /data/d/*",
        {"/data/cut.tgz": OK[:-3]},
    )
    assert r == (
        0,
        b"hello\nbee\n",
        b"\ngzip: stdin: unexpected end of file\n" + CHILD_FAILED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", ["-tzf", "-xzf", "-xOzf"])
@pytest.mark.parametrize("size", [9, 512, 1024])
async def test_a_tar_parse_error_does_not_mask_the_gzip_failure(flags, size):
    bad = gzip.compress(b"x" * size, mtime=0)[:-8] + b"\0" * 8
    notices = (
        (
            b"tar: This does not look like a tar archive\n"
            b"tar: Skipping to next header\n"
        )
        if size >= 512
        else b""
    )
    r = await _shell(f"tar {flags} /data/bad.tgz", {"/data/bad.tgz": bad})
    assert r == (
        2,
        b"",
        b"\ngzip: stdin: invalid compressed data--crc error\n"
        b"\ngzip: stdin: invalid compressed data--length error\n"
        + notices
        + CHILD_FAILED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["t", "x", "c"])
@pytest.mark.parametrize(
    "name, reason",
    [
        ("", "No such file or directory"),
        ("loop", "Too many levels of symbolic links"),
    ],
)
async def test_archive_walk_refusals_keep_the_typed_name(mode, name, reason):
    result = await _shell(
        f"cd /data; ln -s loop loop; tar -{mode}f '{name}' a.txt",
        {"/data/a.txt": b"hello\n"},
    )
    assert result == (
        2,
        b"",
        f"tar: {name}: Cannot open: {reason}\n".encode()
        + b"tar: Error is not recoverable: exiting now\n",
    )


@pytest.mark.asyncio
async def test_cross_mount_tar_keeps_the_empty_archive_refusal():
    ws = Workspace(
        {"/data": RAMVFS(), "/other": RAMVFS()}, mode=MountMode.WRITE
    )
    await ws.shell("echo hello > /other/a.txt")
    result = await ws.shell("cd /data; tar -cf '' /other/a.txt")
    assert result.exit_code == 2
    assert result.stderr == (
        b"tar: : Cannot open: No such file or directory\n"
        b"tar: Error is not recoverable: exiting now\n"
    )


@pytest.mark.parametrize(
    "words,message",
    [
        # argp stops at the first refusal in line order (tar 1.35).
        (["-c", "-x"], MODE_CONFLICT),
        (["-x", "--list"], MODE_CONFLICT),
        (
            ["--strip-components=x", "-c", "-x"],
            "tar: x: Invalid number of elements",
        ),
        (["-c", "-x", "--strip-components=x"], MODE_CONFLICT),
        (["-t", "-f", "/a", "-f", "/a"], MULTIPLE_ARCHIVES),
        (
            ["-t", "--strip-components=-1"],
            "tar: -1: Invalid number of elements",
        ),
        (["-t", "--strip-components="], "tar: : Invalid number of elements"),
        (
            ["-t", "--strip-components=99999999999999999999"],
            "tar: 99999999999999999999: Invalid number of elements",
        ),
    ],
)
def test_parse_flags_refuses_what_tar_refuses(words, message):
    flags = parse_to_kwargs(parse_command(SPECS["tar"], words, "/", "tar"))
    with pytest.raises(UsageError) as exc:
        tar_parse_flags(flags)
    assert (
        str(exc.value) == f"{message}\nTry 'tar --help' for more information."
    )
    assert exc.value.exit_code == 2


@pytest.mark.parametrize(
    "raw,count", [("0", 0), ("+1", 1), (" 2", 2), ("010", 10)]
)
def test_a_strip_count_reads_at_base_ten(raw, count):
    assert strip_count(raw) == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,out",
    [
        (
            "tar --create --file=a.tar a.txt && tar --list --file a.tar",
            "a.txt\n",
        ),
        (
            "tar -cf a.tar a.txt && tar --get -f a.tar --directory=dir && ls dir",
            "a.txt\n",
        ),
        (
            "tar --create --gzip --file=a.tgz a.txt && tar -t --gun -f a.tgz",
            "a.txt\n",
        ),
    ],
)
async def test_tars_long_options_run_as_the_short_ones(line, out):
    ws = Workspace({"/data": RAMVFS()}, mode="write")
    await ws.shell("mkdir /data/dir && printf 'x\\n' > /data/a.txt")
    r = await ws.shell(f"cd /data && {line}")
    assert (r.exit_code, await r.stdout_str()) == (0, out)


@pytest.mark.asyncio
async def test_stdout_archive_needs_no_writable_root_and_does_not_create_dash():
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)}, mode=MountMode.READ)
    await ws.shell("printf hello > /data/a")
    result = await ws.shell("tar -cvf - -C /data a | tar -xOf -")
    assert result.exit_code == 0
    assert await result.materialize_stdout() == b"hello"
    assert await result.materialize_stderr() == b"a\n"
    assert (await ws.shell("test ! -e /-")).exit_code == 0
    await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"", b"not an archive", b"x" * 1024])
@pytest.mark.parametrize("flags", ["-tf", "-xf"])
async def test_invalid_archive_has_tar_diagnostics(data, flags):
    notices = b"tar: This does not look like a tar archive\n"
    if len(data) >= 512:
        notices += b"tar: Skipping to next header\n"
    assert await _shell(f"tar {flags} /data/bad", {"/data/bad": data}) == (
        2,
        b"",
        notices + b"tar: Exiting with failure status due to previous errors\n",
    )
