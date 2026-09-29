from dataclasses import dataclass

from mirage.accessor.base import Accessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.types import FileType, PathSpec
from mirage.vfs.adapter import VFSAdapter


@dataclass(frozen=True, slots=True)
class ReadFixture:
    """A small known file, its parent directory, and an absent sibling."""
    file: PathSpec
    directory: PathSpec
    missing: PathSpec
    content: bytes


async def check_read_contract(adapter: VFSAdapter | CommandIO,
                              accessor: Accessor,
                              fixture: ReadFixture,
                              index: IndexCacheStore = NULL_INDEX) -> None:
    """Verify reads against a caller-owned fixture without mutations.

    Native ranges probe nonempty windows within the fixture. Empty and
    out-of-range reads are normalized by the filesystem operation instead.

    Args:
        adapter (VFSAdapter | CommandIO): adapter being validated.
        accessor (Accessor): fixture's backend client.
        fixture (ReadFixture): file, parent, absent sibling, and bytes.
        index (IndexCacheStore): cache to exercise, if any.
    """
    io = adapter.to_command_io() if isinstance(adapter,
                                               VFSAdapter) else adapter
    data = await io.read_bytes(accessor, fixture.file, index)
    assert data == fixture.content, "read_bytes differs from fixture content"
    info = await io.stat(accessor, fixture.file, index)
    assert info.type == FileType.FILE, "fixture must stat as a file"
    assert info.size is None or info.size == len(
        data), "stat size must be rendered byte length or None"
    parent = await io.stat(accessor, fixture.directory, index)
    assert parent.type == FileType.DIRECTORY, (
        "parent must stat as a directory")
    children = await io.readdir(accessor, fixture.directory, index)
    assert fixture.file.virtual in children, (
        "readdir must include the child virtual path")
    streamed = b"".join(
        [part async for part in io.read_stream(accessor, fixture.file, index)])
    assert streamed == data, "read_stream differs from read_bytes"
    if io.read_range is not None and data:
        offset = min(1, len(data) - 1)
        for size in (min(3, len(data) - offset), None):
            end = None if size is None else offset + size
            actual = await io.read_range(accessor, fixture.file, index, offset,
                                         size)
            assert actual == data[
                offset:end], "read_range must use offset and byte count"
    if io.exists is not None:
        assert await io.exists(
            accessor, fixture.file), "exists rejected the fixture file"
        assert not await io.exists(
            accessor, fixture.missing), "exists accepted a missing file"
    for operation in (io.stat, io.read_bytes):
        try:
            await operation(accessor, fixture.missing, index)
        except FileNotFoundError:
            continue
        raise AssertionError("missing paths must raise FileNotFoundError")
