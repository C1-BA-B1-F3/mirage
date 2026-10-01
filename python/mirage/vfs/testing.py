from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from mirage.accessor.base import Accessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore, RAMIndexCacheStore
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.ops.registry import RegisteredOp
from mirage.types import FileStat, FileType, PathSpec
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.base import BaseVFS


@dataclass(frozen=True, slots=True)
class ReadFixture:
    """A small known file, its parent directory, and an absent sibling."""

    file: PathSpec
    directory: PathSpec
    missing: PathSpec
    content: bytes


async def check_read_contract(
    adapter: VFSAdapter | CommandIO,
    accessor: Accessor,
    fixture: ReadFixture,
    index: IndexCacheStore = NULL_INDEX,
) -> None:
    """Verify reads against a caller-owned fixture without mutations.

    Native ranges probe nonempty windows within the fixture. Empty and
    out-of-range reads are normalized by the filesystem operation instead.

    Args:
        adapter (VFSAdapter | CommandIO): adapter being validated.
        accessor (Accessor): fixture's backend client.
        fixture (ReadFixture): file, parent, absent sibling, and bytes.
        index (IndexCacheStore): cache to exercise, if any.
    """
    io = (
        adapter.to_command_io() if isinstance(adapter, VFSAdapter) else adapter
    )
    data = await io.read_bytes(accessor, fixture.file, index)
    assert data == fixture.content, "read_bytes differs from fixture content"
    info = await io.stat(accessor, fixture.file, index)
    assert info.type == FileType.FILE, "fixture must stat as a file"
    assert info.size is None or info.size == len(data), (
        "stat size must be rendered byte length or None"
    )
    parent = await io.stat(accessor, fixture.directory, index)
    assert parent.type == FileType.DIRECTORY, "parent must stat as a directory"
    children = await io.readdir(accessor, fixture.directory, index)
    assert fixture.file.virtual in children, (
        "readdir must include the child virtual path"
    )
    streamed = b"".join(
        [part async for part in io.read_stream(accessor, fixture.file, index)]
    )
    assert streamed == data, "read_stream differs from read_bytes"
    if io.read_range is not None and data:
        offset = min(1, len(data) - 1)
        for size in (min(3, len(data) - offset), None):
            end = None if size is None else offset + size
            actual = await io.read_range(
                accessor, fixture.file, index, offset, size
            )
            assert actual == data[offset:end], (
                "read_range must use offset and byte count"
            )
    if io.exists is not None:
        assert await io.exists(accessor, fixture.file), (
            "exists rejected the fixture file"
        )
        assert not await io.exists(accessor, fixture.missing), (
            "exists accepted a missing file"
        )
    for operation in (io.stat, io.read_bytes):
        try:
            await operation(accessor, fixture.missing, index)
        except FileNotFoundError:
            continue
        raise AssertionError("missing paths must raise FileNotFoundError")


class DriverOps:
    """A driver's op table, callable the way a mount calls it.

    The accessor is bound, one index store lives per instance, and every
    call follows the mount's argument conventions, so a driver can be
    exercised, or scripted, without a ``Workspace``. A verb the table does
    not carry raises the same ``no op registered`` a mount answers with.

    Args:
        vfs (BaseVFS): the driver to call.
        index (IndexCacheStore | None): the store to hand every op; a RAM
            store at the driver's ``index_ttl`` by default.
    """

    def __init__(
        self, vfs: BaseVFS, index: IndexCacheStore | None = None
    ) -> None:
        self.vfs = vfs
        self.index = (
            index
            if index is not None
            else RAMIndexCacheStore(ttl=vfs.index_ttl)
        )

    def op(self, name: str) -> RegisteredOp:
        """The registration serving ``name`` for every filetype.

        Args:
            name (str): the op name.
        """
        for ro in self.vfs.ops():
            if ro.name == name and ro.filetype is None:
                return ro
        raise KeyError(f"no op registered: {name!r} for VFS {self.vfs.name!r}")

    def has(self, name: str) -> bool:
        """Whether the table serves ``name`` for every filetype.

        Args:
            name (str): the op name.
        """
        return any(
            ro.name == name and ro.filetype is None for ro in self.vfs.ops()
        )

    async def call(
        self, name: str, path: PathSpec, *args: Any, **kwargs: Any
    ) -> Any:
        """Call op ``name`` on ``path`` with the driver's accessor.

        Args:
            name (str): the op name.
            path (PathSpec): the op's path, keyed below the mount.
            *args (Any): positional op arguments (a write's bytes).
            **kwargs (Any): op keywords; ``index`` defaults to this
                instance's store.
        """
        kwargs.setdefault("index", self.index)
        return await self.op(name).fn(self.vfs.accessor, path, *args, **kwargs)

    async def read(self, path: PathSpec, **kwargs: Any) -> bytes:
        return cast(bytes, await self.call("read", path, **kwargs))

    async def readdir(self, path: PathSpec) -> list[str]:
        return cast(list[str], await self.call("readdir", path))

    async def stat(self, path: PathSpec) -> FileStat:
        return cast(FileStat, await self.call("stat", path))

    async def glob(self, path: PathSpec) -> list[PathSpec]:
        return cast(list[PathSpec], await self.call("glob", path))

    async def write(self, path: PathSpec, data: bytes) -> None:
        await self.call("write", path, data)

    async def append(self, path: PathSpec, data: bytes) -> None:
        await self.call("append", path, data)

    async def create(self, path: PathSpec) -> None:
        await self.call("create", path)

    async def mkdir(self, path: PathSpec, parents: bool = False) -> None:
        await self.call(
            "mkdir", path, **({"parents": True} if parents else {})
        )

    async def unlink(self, path: PathSpec) -> None:
        await self.call("unlink", path)

    async def rmdir(self, path: PathSpec) -> None:
        await self.call("rmdir", path)

    async def rename(self, src: PathSpec, dst: PathSpec) -> None:
        await self.call("rename", src, dst)

    async def truncate(self, path: PathSpec, length: int) -> None:
        await self.call("truncate", path, length)


async def _joined(value: bytes | AsyncIterator[bytes]) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return b"".join([chunk async for chunk in value])


async def check_driver_contract(
    vfs: BaseVFS, fixture: ReadFixture, index: IndexCacheStore | None = None
) -> None:
    """Verify a driver's read ops against a caller-owned fixture.

    The driver-level twin of :func:`check_read_contract`: the checks run
    through the table ``vfs.ops()`` serves, the one channel a mount
    dispatches to, so they hold for a builtin-shaped subclass as much as
    for a driver built from an adapter. The ``read`` op's window is always
    probed, since the op slices a whole read when the table has no native
    range. Nothing is mutated.

    Args:
        vfs (BaseVFS): the driver being validated.
        fixture (ReadFixture): file, parent, absent sibling, and bytes.
        index (IndexCacheStore | None): the store to hand every op; a RAM
            store at the driver's ``index_ttl`` by default.
    """
    table = DriverOps(vfs, index)
    data = await _joined(await table.read(fixture.file))
    assert data == fixture.content, "read differs from fixture content"
    info = await table.stat(fixture.file)
    assert info.type == FileType.FILE, "fixture must stat as a file"
    assert info.size is None or info.size == len(data), (
        "stat size must be rendered byte length or None"
    )
    parent = await table.stat(fixture.directory)
    assert parent.type == FileType.DIRECTORY, "parent must stat as a directory"
    children = await table.readdir(fixture.directory)
    assert fixture.file.virtual in children, (
        "readdir must include the child virtual path"
    )
    if data:
        offset = min(1, len(data) - 1)
        for size in (min(3, len(data) - offset), None):
            end = None if size is None else offset + size
            actual = await _joined(
                await table.read(fixture.file, offset=offset, size=size)
            )
            assert actual == data[offset:end], (
                "read must use offset and byte count"
            )
    for operation in (table.stat, table.read):
        try:
            await operation(fixture.missing)
        except FileNotFoundError:
            continue
        raise AssertionError("missing paths must raise FileNotFoundError")
