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

from mirage import MountMode, Workspace
from mirage.io import IOResult
from mirage.ops.registry import op
from mirage.types import PathSpec
from mirage.vfs.ram import RAMVFS

# A raw read is what read-modify-write needs: FUSE hands the merged
# buffer straight back to ``write``, which always stores, so a read that
# rendered would store the rendering over the file. Two things can serve
# a rendering, and ``raw`` has to defeat both: a filetype-scoped op the
# mount registers for the extension, and the file cache a command's
# rendered read already filled under the same path.


@op("read", vfs="ram", filetype=".tally")
async def _read_tally(accessor, path: PathSpec, **kwargs) -> bytes:
    return b"RENDERED"


class _CachingRAM(RAMVFS):
    caches_reads = True


def _workspace(vfs: RAMVFS) -> Workspace:
    ws = Workspace({"/data/": vfs}, mode=MountMode.WRITE)
    ws.mount("/data/").register_fns([_read_tally])
    return ws


@pytest.mark.asyncio
async def test_read_resolves_the_filetype_op():
    ws = _workspace(RAMVFS())
    await ws.vfs.write("/data/books.tally", b"STORED")
    assert await ws.vfs.read("/data/books.tally") == b"RENDERED"


@pytest.mark.asyncio
async def test_raw_read_skips_the_filetype_op():
    ws = _workspace(RAMVFS())
    await ws.vfs.write("/data/books.tally", b"STORED")
    assert await ws.vfs.read("/data/books.tally", raw=True) == b"STORED"


@pytest.mark.asyncio
async def test_raw_read_leaves_an_unregistered_extension_alone():
    ws = _workspace(RAMVFS())
    await ws.vfs.write("/data/notes.txt", b"plain")
    assert await ws.vfs.read("/data/notes.txt", raw=True) == b"plain"


@pytest.mark.asyncio
async def test_raw_read_is_not_served_from_the_file_cache():
    # The file cache is keyed on the path alone, so a raw read of a path
    # whose cached entry may be a rendering must not be served it.
    ws = _workspace(_CachingRAM())
    await ws.vfs.write("/data/books.tally", b"STORED")
    # Distinct from both the stored and the rendered bytes, so a warm hit
    # is distinguishable from either op running.
    await ws.apply_io(
        IOResult(
            reads={"/data/books.tally": b"CACHED"}, cache=["/data/books.tally"]
        )
    )
    assert await ws.vfs.read("/data/books.tally", raw=True) == b"STORED"


class _RenderingRAM(_CachingRAM):
    """A VFS that ships the renderer itself, as gdocs does, so its own
    command reads already return what the filetype op renders."""

    def ops(self):
        return [*super().ops(), *_read_tally._registered_ops]


async def _seed(ws: Workspace, path: str) -> None:
    await ws.vfs.write(path, b"STORED")
    await ws.apply_io(IOResult(reads={path: b"CACHED"}, cache=[path]))


@pytest.mark.asyncio
async def test_a_user_renderer_is_never_served_from_the_file_cache():
    # Commands fill the cache with what their own reads return, which a
    # renderer registered on the mount never sees: serving the entry would
    # answer a rendered read with raw bytes.
    ws = _workspace(_CachingRAM())
    await _seed(ws, "/data/books.tally")
    assert await ws.vfs.read("/data/books.tally") == b"RENDERED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        "cat /data/books.tally",
        "echo T | tee /data/books.tally",
    ],
    ids=["cat", "tee"],
)
async def test_a_user_renderer_renders_after_a_shell_command(line):
    ws = _workspace(_CachingRAM())
    await ws.vfs.write("/data/books.tally", b"STORED\n")
    result = await ws.shell(line)
    await result.materialize_stdout()
    assert result.exit_code == 0
    assert await ws.cache.exists("/data/books.tally")
    assert await ws.vfs.read("/data/books.tally") == b"RENDERED"


@pytest.mark.asyncio
async def test_a_renderer_named_by_filetype_is_never_served_warm():
    ws = _workspace(_CachingRAM())
    await _seed(ws, "/data/notes.txt")
    data, _ = await ws.dispatch(
        "read", PathSpec.from_str_path("/data/notes.txt"), filetype=".tally"
    )
    assert data == b"RENDERED"


@pytest.mark.asyncio
async def test_a_vfs_own_renderer_is_still_served_from_the_file_cache():
    ws = Workspace({"/data/": _RenderingRAM()}, mode=MountMode.WRITE)
    await _seed(ws, "/data/books.tally")
    assert await ws.vfs.read("/data/books.tally") == b"CACHED"


@pytest.mark.asyncio
async def test_a_plain_path_beside_a_user_renderer_is_still_served_warm():
    ws = _workspace(_CachingRAM())
    await _seed(ws, "/data/notes.txt")
    assert await ws.vfs.read("/data/notes.txt") == b"CACHED"


@pytest.mark.asyncio
async def test_a_warm_cache_still_answers_a_ranged_read_with_the_window():
    # The cache holds the whole object; a ranged read asked for a
    # window instead of the file, so serving the file back is wrong.
    # git reads pack indexes this way (4 bytes at a known offset), and
    # the dispatcher is the door it reaches too.
    ws = _workspace(_CachingRAM())
    await ws.vfs.write("/data/f.bin", b"0123456789")
    await ws.apply_io(
        IOResult(reads={"/data/f.bin": b"0123456789"}, cache=["/data/f.bin"])
    )
    assert await ws.vfs.read("/data/f.bin", 2, 3) == b"234"
    assert await ws.vfs.read("/data/f.bin") == b"0123456789"
    assert await ws.vfs.read("/data/f.bin", 7) == b"789"
    assert await ws.vfs.read("/data/f.bin", 2, 0) == b""
    assert await ws.vfs.read("/data/f.bin", 99, 3) == b""


@pytest.mark.asyncio
async def test_a_cold_and_a_warm_ranged_read_agree():
    ws = _workspace(_CachingRAM())
    await ws.vfs.write("/data/f.bin", b"0123456789")
    cold = await ws.vfs.read("/data/f.bin", 2, 3)
    await ws.apply_io(
        IOResult(reads={"/data/f.bin": b"0123456789"}, cache=["/data/f.bin"])
    )
    assert await ws.vfs.read("/data/f.bin", 2, 3) == cold


@op("read", vfs="ram", filetype=".tally")
async def _read_tally_override(accessor, path: PathSpec, **kwargs) -> bytes:
    return b"USER"


@pytest.mark.asyncio
async def test_a_user_override_of_a_vfs_renderer_is_never_served_warm():
    # Same key as the renderer the VFS ships, a different op: the commands
    # still read through the VFS, so the entry is not this rendering.
    ws = Workspace({"/data/": _RenderingRAM()}, mode=MountMode.WRITE)
    ws.mount("/data/").register_fns([_read_tally_override])
    await _seed(ws, "/data/books.tally")
    assert await ws.vfs.read("/data/books.tally") == b"USER"


@pytest.mark.asyncio
async def test_an_extensionless_path_beside_a_user_renderer_is_served_warm():
    ws = _workspace(_CachingRAM())
    await _seed(ws, "/data/README")
    assert await ws.vfs.read("/data/README") == b"CACHED"
