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
import errno
import gc

import pytest

from mirage import Workspace
from mirage.accessor.ram import RAMAccessor
from mirage.commands.config import command
from mirage.commands.spec import CommandSpec
from mirage.commands.spec.types import Option
from mirage.io.types import IOResult, materialize
from mirage.observe.context import revision_for
from mirage.ops.registry import op
from mirage.types import MountMode, PathSpec
from mirage.utils.errors import OperationNotSupportedError, ReadOnlyError
from mirage.vfs.ram import RAMVFS
from mirage.workspace.mount import MountRegistry
from mirage.workspace.mount.mount import MountEntry


def _run(coro):
    return asyncio.run(coro)


# ── prefix validation ──────────────────────────


def test_mount_accepts_root_prefix():
    m = MountEntry("/", RAMVFS())
    assert m.prefix == "/"


def test_mount_rejects_no_leading_slash():
    with pytest.raises(ValueError, match="must start with /"):
        MountEntry("data/", RAMVFS())


def test_mount_rejects_no_trailing_slash():
    with pytest.raises(ValueError, match="must end with /"):
        MountEntry("/data", RAMVFS())


def test_mount_rejects_double_slash():
    with pytest.raises(ValueError, match="must not contain //"):
        MountEntry("/data//sub/", RAMVFS())


def test_mount_valid_prefix():
    m = MountEntry("/data/", RAMVFS())
    assert m.prefix == "/data/"


# ── read-only enforcement ──────────────────────


def test_read_only_blocks_write_ops():
    reg = MountRegistry()
    reg.mount("/ro/", RAMVFS(), MountMode.READ)
    mount = reg.mount_for("/ro/file.txt")
    with pytest.raises(ReadOnlyError, match="Read-only"):
        _run(mount.execute_op("write", "/file.txt", data=b"x"))


def test_write_mode_allows_write_ops():
    reg = MountRegistry()
    reg.mount("/rw/", RAMVFS(), MountMode.WRITE)
    mount = reg.mount_for("/rw/file.txt")
    _run(mount.execute_op("write", "/new.txt", data=b"hello"))


def test_read_only_blocks_write_cmd():
    reg = MountRegistry()
    reg.mount("/ro/", RAMVFS(), MountMode.READ)
    mount = reg.mount_for("/ro/file.txt")
    scope = PathSpec(vfs_path="ro/newdir",
                     virtual="/ro/newdir",
                     directory="/ro/",
                     resolved=True)
    stdout, io = _run(mount.execute_cmd("mkdir", [scope], [], {}))
    assert io.exit_code != 0
    assert io.stderr == (b"mkdir: cannot create directory '/ro/newdir': "
                         b"Read-only file system\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [MountMode.READ, MountMode.WRITE])
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("flag", ["help", "version"])
async def test_only_wrapper_responses_bypass_the_write_guard(
        mode, declared, flag):
    vfs = RAMVFS()
    mount = MountEntry("/ram/", vfs, mode)
    calls: list[str] = []
    options = (Option(long="--version", type="bool"), ) if declared else ()

    @command("mutate",
             vfs="ram",
             spec=CommandSpec(options=options),
             write=True)
    async def mutate(accessor: RAMAccessor, paths, texts, opts):
        calls.append("handler")
        accessor.store.files["/changed"] = b"changed"
        return b"custom version\n", IOResult()

    mount.register_fns([mutate])
    stdout, io = await mount.execute_cmd("mutate", [], [], {flag: True})
    output = await materialize(stdout)
    if declared and flag == "version":
        if mode == MountMode.READ:
            assert io.exit_code == 1
            assert io.stderr == b"mutate: read-only mount at /ram/\n"
            assert not calls
            assert "/changed" not in vfs.accessor.store.files
        else:
            assert io.exit_code == 0
            assert output == b"custom version\n"
            assert calls == ["handler"]
            assert vfs.accessor.store.files["/changed"] == b"changed"
    else:
        assert io.exit_code == 0
        assert output
        assert not calls
        assert "/changed" not in vfs.accessor.store.files


@pytest.mark.asyncio
async def test_the_read_only_refusal_is_newline_terminated():
    # stderr accumulates across a line, so an unterminated refusal ran
    # into the next one: `{ sync /ro/a; sync /ro/b; }` printed the single
    # line `sync: read-only mount at /ro/sync: read-only mount at /ro/`.
    mount = MountEntry("/ro/", RAMVFS(), MountMode.READ)

    @command("sync", vfs="ram", spec=CommandSpec(), write=True)
    async def sync(accessor: RAMAccessor, paths, texts, opts):
        return None, IOResult()

    mount.register_fns([sync])
    _, io = await mount.execute_cmd("sync", [], [], {})
    assert io.stderr == b"sync: read-only mount at /ro/\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [MountMode.READ, MountMode.WRITE])
@pytest.mark.parametrize("path_guarded", [False, True])
async def test_only_a_write_command_the_door_cannot_see_is_refused_up_front(
        mode, path_guarded):
    # A path-guarded command's writes go through the guarded op slots,
    # which refuse each one where it happens, so a read-only mount runs
    # it like a reader (`gzip -c`, `split -n 1/2`). A write command that
    # reaches its service some other way has no door to refuse it, so
    # the mount refuses it before it runs.
    vfs = RAMVFS()
    mount = MountEntry("/ram/", vfs, mode)
    calls: list[int] = []

    @command("filter",
             vfs="ram",
             spec=CommandSpec(),
             write=True,
             path_guarded=path_guarded)
    async def filter_cmd(accessor: RAMAccessor, paths, texts, opts):
        calls.append(len(paths))
        return b"ran\n", IOResult()

    mount.register_fns([filter_cmd])
    paths = [PathSpec.from_str_path("/ram/a")]
    stdout, io = await mount.execute_cmd("filter", paths, [], {})
    if mode == MountMode.READ and not path_guarded:
        assert io.exit_code == 1
        assert io.stderr == b"filter: read-only mount at /ram/\n"
        assert not calls
    else:
        assert io.exit_code == 0
        assert await materialize(stdout) == b"ran\n"
        assert calls == [1]


def test_write_mode_allows_write_cmd():
    reg = MountRegistry()
    reg.mount("/rw/", RAMVFS(), MountMode.WRITE)
    mount = reg.mount_for("/rw/file.txt")
    scope = PathSpec(vfs_path="rw/newdir",
                     virtual="/rw/newdir",
                     directory="/rw/",
                     resolved=True)
    stdout, io = _run(mount.execute_cmd("mkdir", [scope], [], {}))
    assert io.exit_code == 0


def test_read_only_allows_read_cmd():
    reg = MountRegistry()
    reg.mount("/ro/", RAMVFS(), MountMode.READ)
    mount = reg.mount_for("/ro/")
    scope = PathSpec(vfs_path="ro",
                     virtual="/ro/",
                     directory="/ro/",
                     resolved=False)
    stdout, io = _run(mount.execute_cmd("ls", [scope], [], {}))
    assert io.exit_code == 0


# ── execute_cmd ────────────────────────────────


def test_execute_cmd_cat(registry):
    mount = registry.mount_for("/data/hello.txt")
    scope = PathSpec(vfs_path="data/hello.txt",
                     virtual="/data/hello.txt",
                     directory="/data/",
                     resolved=True)
    stdout, io = _run(mount.execute_cmd("cat", [scope], [], {}))
    assert io.exit_code == 0
    assert stdout is not None


def test_execute_cmd_not_found(registry):
    mount = registry.mount_for("/data/hello.txt")
    stdout, io = _run(mount.execute_cmd("nonexistent_cmd", [], [], {}))
    assert io.exit_code == 127
    assert b"command not found" in io.stderr


def test_execute_cmd_ls(registry):
    mount = registry.mount_for("/data/hello.txt")
    scope = PathSpec(vfs_path="data",
                     virtual="/data/",
                     directory="/data/",
                     resolved=False)
    stdout, io = _run(mount.execute_cmd("ls", [scope], [], {}))
    assert io.exit_code == 0


def test_execute_cmd_with_flag_kwargs(registry):
    mount = registry.mount_for("/data/hello.txt")
    scope = PathSpec(vfs_path="data/hello.txt",
                     virtual="/data/hello.txt",
                     directory="/data/",
                     resolved=True)
    stdout, io = _run(mount.execute_cmd("cat", [scope], [], {"n": True}))
    assert io.exit_code == 0


def test_execute_cmd_with_texts(registry):
    mount = registry.mount_for("/data/hello.txt")
    scope = PathSpec(vfs_path="data/hello.txt",
                     virtual="/data/hello.txt",
                     directory="/data/",
                     resolved=True)
    stdout, io = _run(mount.execute_cmd("grep", [scope], ["hello"], {}))
    assert io.exit_code == 0


# ── execute_op ─────────────────────────────────


def test_execute_op_stat(registry):
    mount = registry.mount_for("/data/hello.txt")
    result = _run(mount.execute_op("stat", "/hello.txt"))
    assert result is not None
    assert result.size > 0


def test_execute_op_readdir(registry):
    mount = registry.mount_for("/data/")
    result = _run(mount.execute_op("readdir", "/"))
    assert isinstance(result, list)
    assert len(result) > 0


def test_execute_op_no_such_op(registry):
    mount = registry.mount_for("/data/hello.txt")
    with pytest.raises(OperationNotSupportedError, match="no op") as exc_info:
        _run(mount.execute_op("nonexistent_op", "/file.txt"))
    assert exc_info.value.filename == "/file.txt"
    assert exc_info.value.errno == errno.ENOTSUP


@op("read", vfs="ram", filetype=".tally")
async def _read_tally(accessor, path: PathSpec, **kwargs) -> bytes:
    return b"RENDERED"


def _refuse_whole(accessor, scope, *args, **kwargs):
    raise AssertionError("a streamed read must not run the whole read")


def _pinned_stream(accessor, scope, *args, **kwargs):

    async def body():
        yield (revision_for(scope.virtual) or "unpinned").encode()

    return body()


def _stream_registry() -> tuple[MountRegistry, MountEntry]:
    vfs = RAMVFS()
    vfs._store.files["/f.txt"] = b"stored\n"
    vfs._store.files["/books.tally"] = b"STORED"
    reg = MountRegistry()
    reg.mount("/data/", vfs, MountMode.WRITE)
    mount = reg.mount_for("/data/f.txt")
    mount.register_fns([_read_tally])
    return reg, mount


@pytest.mark.asyncio
async def test_execute_op_with_stream_answers_from_the_ops_stream_form(
        monkeypatch):
    _, mount = _stream_registry()
    whole = await mount.execute_op("read", "/data/f.txt")
    assert whole == b"stored\n"
    monkeypatch.setattr(mount._ops[("read", None)], "fn", _refuse_whole)
    stream = await mount.execute_op("read", "/data/f.txt", stream=True)
    assert not isinstance(stream, (bytes, bytearray))
    assert hasattr(stream, "__aiter__")
    assert b"".join([chunk async for chunk in stream]) == b"stored\n"


@pytest.mark.asyncio
async def test_a_filetype_read_without_a_stream_form_still_wins():
    _, mount = _stream_registry()
    assert mount._ops[("read", ".tally")].stream is None
    rendered = await mount.execute_op("read", "/data/books.tally", stream=True)
    assert rendered == b"RENDERED"
    raw = await mount.execute_op("read",
                                 "/data/books.tally",
                                 stream=True,
                                 filetype=None)
    assert b"".join([chunk async for chunk in raw]) == b"STORED"


@pytest.mark.asyncio
async def test_a_streamed_read_sees_the_mounts_revision_pins(monkeypatch):
    _, mount = _stream_registry()
    mount.revisions = {"/data/f.txt": "v1"}
    monkeypatch.setattr(mount._ops[("read", None)], "stream", _pinned_stream)
    stream = await mount.execute_op("read", "/data/f.txt", stream=True)
    assert revision_for("/data/f.txt") is None
    assert [chunk async for chunk in stream] == [b"v1"]


@pytest.mark.asyncio
async def test_a_dropped_stream_releases_its_mount_when_collected():
    vfs = RAMVFS()
    vfs._store.files["/f.txt"] = b"stored\n"
    ws = Workspace({"/data/": vfs}, mode=MountMode.WRITE)
    mount = ws._registry.mount_for("/data/f.txt")
    stream = await mount.execute_op("read", "/data/f.txt", stream=True)
    assert await anext(stream) == b"stored\n"
    waiting = asyncio.create_task(mount.activity.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    del stream
    gc.collect()
    await asyncio.wait_for(waiting, 1)
    await asyncio.wait_for(ws.unmount("/data/"), 2)
    assert "/data/" not in [m.prefix for m in ws._registry.mounts()]


@pytest.mark.asyncio
async def test_a_dropped_stream_closes_its_backend_before_the_vfs_closes(
        monkeypatch):
    events: list[str] = []
    vfs = RAMVFS()
    vfs._store.files["/f.txt"] = b"stored\n"

    async def close() -> None:
        events.append("vfs close")

    def logged_stream(accessor, scope, *args, **kwargs):

        async def body():
            try:
                yield b"one"
                yield b"two"
            finally:
                await asyncio.sleep(0.05)
                events.append("backend finally")

        return body()

    monkeypatch.setattr(vfs, "close", close)
    ws = Workspace({"/data/": vfs}, mode=MountMode.WRITE)
    mount = ws._registry.mount_for("/data/f.txt")
    monkeypatch.setattr(mount._ops[("read", None)], "stream", logged_stream)
    stream = await mount.execute_op("read", "/data/f.txt", stream=True)
    assert await anext(stream) == b"one"
    unmounting = asyncio.create_task(ws.unmount("/data/"))
    await asyncio.sleep(0.01)
    assert not unmounting.done()
    del stream
    gc.collect()
    await asyncio.wait_for(unmounting, 2)
    assert events == ["backend finally", "vfs close"]
    await ws.close()


# ── command resolution ─────────────────────────


def test_resolve_command_exists(registry):
    mount = registry.mount_for("/data/hello.txt")
    cmd = mount.resolve_command("cat")
    assert cmd is not None
    assert cmd.name == "cat"


def test_resolve_command_missing(registry):
    mount = registry.mount_for("/data/hello.txt")
    cmd = mount.resolve_command("nonexistent")
    assert cmd is None


@pytest.mark.asyncio
async def test_a_path_guarded_command_is_still_held_at_its_write():
    vfs = RAMVFS()
    vfs._store.files["/a"] = b"original"
    mount = MountEntry("/ram/", vfs, MountMode.READ)
    cmd = next(cmd for cmd in vfs.commands() if cmd.name == "gzip")
    assert cmd.path_guarded
    mount.register(cmd)
    # The write is refused where it happens and gzip says so in its own
    # words (the fatal write_error form), leaving the store untouched.
    _, io = await mount.execute_cmd("gzip", [PathSpec.from_str_path("/ram/a")],
                                    [], {})
    assert (io.exit_code,
            io.stderr) == (1, b"\ngzip: /ram/a.gz: Read-only file system\n")
    assert vfs._store.files == {"/a": b"original"}


@pytest.mark.asyncio
async def test_repeated_dev_pipelines_leave_no_stream_held():
    ws = Workspace({"/data/": RAMVFS()}, mode=MountMode.WRITE)
    dev = next(m for m in ws.mounts() if m.prefix == "/dev/")
    for _ in range(5):
        result = await ws.shell("cat /dev/zero | head -c 4")
        assert await result.stdout_str() == "\0" * 4
        del result
    gc.collect()
    await asyncio.wait_for(dev.activity.wait(), 2)
    await ws.close()
