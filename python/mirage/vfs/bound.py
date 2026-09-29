from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from mirage.cache.index import IndexCacheStore, IndexConfig
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.base import BaseVFS

_DIRECT_OPS: dict[str, str] = {
    "readdir": "readdir",
    "read_bytes": "read_bytes",
    "range_read": "read_range",
    "read_stream": "read_stream",
    "stat": "stat",
    "write": "write",
    "append": "append",
    "create": "create",
    "mkdir": "mkdir",
    "unlink": "unlink",
    "rmdir": "rmdir",
    "rm_recursive": "rm_r",
    "rename": "rename",
    "copy": "copy",
    "truncate": "truncate",
    "exists": "exists",
    "find_flat": "find",
}


def range_adapter(
    fn: Callable[..., Awaitable[bytes]],
    index: Callable[[], IndexCacheStore],
) -> Callable[..., Awaitable[bytes]]:
    """Adapt a table's ``read_range`` slot to the VFS API's shape.

    The one field whose two callers disagree about more than a name. A
    builtin publishes ``range_read(accessor, path, start, end)`` with the
    end exclusive, while the table slot is ``(accessor, path, index,
    offset, size)``, and ``BaseVFS.__getattr__`` binds only the
    accessor. Forwarded raw, the table function took ``start`` as its
    index and ``end`` as its offset, so an object-store table read from
    ``end`` to EOF instead of the window asked for, and one that touched
    the index at all crashed on an int.

    The index is read per call rather than captured, because
    ``set_index`` can replace the store after construction.

    Args:
        fn (Callable): the table's ``read_range`` slot.
        index (Callable): reads the owning VFS's current index.
    """

    async def range_read(accessor: Any, path: PathSpec, start: int,
                         end: int) -> bytes:
        return await fn(accessor, path, index(), start, end - start)

    return range_read


def direct_ops(
    io: CommandIO,
    index: Callable[[], IndexCacheStore],
) -> dict[str, Callable[..., Any]]:
    """Derive the direct filesystem surface from the operation table.

    Args:
        io (CommandIO): callbacks shared with commands and filesystem ops.
        index (Callable): supplies the current index for range adaptation.
    """
    ops: dict[str, Callable[..., Any]] = {}
    for name, field in _DIRECT_OPS.items():
        fn = getattr(io, field)
        if fn is None:
            continue
        ops[name] = (range_adapter(fn, index) if field == "read_range" else fn)
    if io.du is not None:
        ops["du_size"] = io.du.size
        ops["du_entries"] = io.du.entries
    return ops


class BoundVFS(BaseVFS):
    """Bind direct filesystem calls to the same table as commands and ops."""

    def __init__(self,
                 *,
                 io: CommandIO | VFSAdapter,
                 index: IndexConfig | None = None) -> None:
        super().__init__(index=index)
        self.io = io.to_command_io() if isinstance(io, VFSAdapter) else io
        self._ops = direct_ops(self.io, lambda: self.index)

    async def resolve_glob(
            self,
            paths: list[PathSpec],
            prefix: str = "",
            index: IndexCacheStore | None = None) -> list[PathSpec]:
        if prefix:
            paths = [
                replace(p, vfs_path=mount_key(p.virtual, prefix))
                for p in paths
            ]
        return await self.io.resolve_glob(
            self.accessor, paths, index if index is not None else self.index)
