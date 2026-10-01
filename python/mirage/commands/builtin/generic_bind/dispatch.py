from collections.abc import AsyncIterator
from dataclasses import replace
from typing import cast

from mirage.accessor.base import Accessor, NOOPAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.commands.builtin.generic_bind.adapter import Builder, CommandIO
from mirage.commands.config import CommandOpts
from mirage.io.stream import materialize
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import FileStat, PathSpec
from mirage.utils.stream import ensure_stream


def _mounted(accessor: Accessor) -> bool:
    return True


def dispatch_io(dispatch: DispatchFn) -> CommandIO:
    """Bind generic read operations to the workspace's virtual namespace.

    Args:
        dispatch (DispatchFn): policy-checked operation dispatcher.
    """
    async def readdir(accessor: Accessor, path: PathSpec,
                      index: IndexCacheStore = NULL_INDEX) -> list[str]:
        data, _ = await dispatch("readdir", path)
        return cast(list[str], data)

    async def stat(accessor: Accessor, path: PathSpec,
                   index: IndexCacheStore = NULL_INDEX) -> FileStat:
        data, _ = await dispatch("stat", path, nofollow=True)
        return cast(FileStat, data)

    async def read_bytes(accessor: Accessor, path: PathSpec,
                         index: IndexCacheStore = NULL_INDEX) -> bytes:
        data, _ = await dispatch("read", path)
        return await materialize(data) or b""

    async def read_stream(accessor: Accessor, path: PathSpec,
                          index: IndexCacheStore = NULL_INDEX
                          ) -> AsyncIterator[bytes]:
        data, _ = await dispatch("read", path)
        async for chunk in ensure_stream(data):
            yield chunk

    return CommandIO(readdir=readdir, stat=stat, read_bytes=read_bytes,
                     read_stream=read_stream, is_mounted=_mounted)


async def run_dispatch(
    builder: Builder, paths: list[PathSpec], texts: list[str],
    opts: CommandOpts, dispatch: DispatchFn
) -> tuple[ByteSource | None, IOResult]:
    """Run the same builder once across every operand's owning mount.

    Args:
        builder (Builder): the command's existing generic binding.
        paths (list[PathSpec]): operands in command-line order.
        texts (list[str]): text operands.
        opts (CommandOpts): invocation flags and namespace.
        dispatch (DispatchFn): policy-checked operation dispatcher.
    """
    paths = [replace(p, vfs_path=p.virtual.strip("/")) for p in paths]
    if opts.ns is not None:
        opts = replace(opts, ns=replace(opts.ns, mounts=None))
    result = await builder.fn(dispatch_io(dispatch), NOOPAccessor(), paths,
                            texts, opts)
    return result if result is not None else (None, IOResult())
