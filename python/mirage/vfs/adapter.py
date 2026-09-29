from dataclasses import dataclass, field
from functools import partial

from mirage.accessor.base import Accessor
from mirage.commands.builtin.generic.du import DEFAULT_MAX_DU_ENTRIES
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.commands.builtin.utils.wrap import stream_from_bytes
from mirage.types import PathSpec
from mirage.utils.glob_walk import DEFAULT_MAX_GLOB_MATCHES
from mirage.vfs.types import (IsMountedOp, NativeReadOps, ReadBytesOp, ReadOps,
                              SearchOps, StatOp, WriteOp, WriteOps)


def _mounted(accessor: Accessor) -> bool:
    return True


async def _exists(stat: StatOp, accessor: Accessor, path: PathSpec) -> bool:
    try:
        await stat(accessor, path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


@dataclass(frozen=True, kw_only=True)
class VFSAdapter:
    """Compose resource capabilities into the command and dispatcher table.

    Args:
        read (ReadOps): required listing, byte read, and stat operations.
        native (NativeReadOps): optional accelerators; byte streaming and
            existence checks otherwise derive from the required reads.
        writes (WriteOps): independent mutations, absent by default.
        search (SearchOps | None): optional native text search.
        local (bool): whether data lives on the host filesystem.
        is_mounted (IsMountedOp): optional backend availability check.
        max_glob_matches (int | None): glob expansion ceiling.
        max_du_entries (int | None): size traversal ceiling.
    """

    read: ReadOps
    native: NativeReadOps = field(default_factory=NativeReadOps)
    writes: WriteOps = field(default_factory=WriteOps)
    search: SearchOps | None = None
    local: bool = False
    is_mounted: IsMountedOp = _mounted
    max_glob_matches: int | None = DEFAULT_MAX_GLOB_MATCHES
    max_du_entries: int | None = DEFAULT_MAX_DU_ENTRIES

    def to_command_io(self) -> CommandIO:
        """Build one table shared by commands, globbing, and filesystem ops."""
        return CommandIO(
            readdir=self.read.readdir,
            read_bytes=self.read.read_bytes,
            streams_bytes=self.native.read_stream is None,
            stat=self.read.stat,
            read_stream=self.native.read_stream
            or partial(stream_from_bytes, self.read.read_bytes),
            read_range=self.native.read_range,
            exists=self.native.exists or partial(_exists, self.read.stat),
            find=self.native.find,
            du=self.native.du,
            write=self.writes.write,
            append=self.writes.append,
            create=self.writes.create,
            mkdir=self.writes.mkdir,
            unlink=self.writes.unlink,
            rmdir=self.writes.rmdir,
            rm_r=self.writes.rm_r,
            rename=self.writes.rename,
            copy=self.writes.copy,
            dir_copy=self.writes.dir_copy,
            truncate=self.writes.truncate,
            set_attrs=self.writes.set_attrs,
            search=self.search,
            local=self.local,
            is_mounted=self.is_mounted,
            max_glob_matches=self.max_glob_matches,
            max_du_entries=self.max_du_entries,
        )


def append_from_read(read: ReadBytesOp, write: WriteOp) -> WriteOp:
    """Explicitly opt a byte store into non-atomic read/modify/write append.

    Args:
        read (ReadBytesOp): whole-file reader; only ENOENT means empty.
        write (WriteOp): whole-file replacement.
    """

    async def append(accessor: Accessor, path: PathSpec, data: bytes) -> None:
        try:
            previous = await read(accessor, path)
        except FileNotFoundError:
            previous = b""
        await write(accessor, path, previous + data)

    return append
