from mirage.accessor.base import Accessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.types import FileType, PathSpec
from mirage.utils.key_prefix import mount_key, mount_prefix_of
from mirage.vfs.types import DuEntries, DuOps, ReaddirOp, StatOp


async def walk(
    stat: StatOp,
    readdir: ReaddirOp,
    accessor: Accessor,
    path: PathSpec,
    index: IndexCacheStore,
    results: list[tuple[str, int]] | None,
) -> int:
    """Sum file sizes under a path through readdir and stat.

    Only absence counts as zero; any other failure propagates rather than
    under-reporting the total.

    Args:
        stat (StatOp): the backend's stat.
        readdir (ReaddirOp): the backend's readdir.
        accessor (Accessor): backend handle.
        path (PathSpec): directory or file to walk.
        index (IndexCacheStore): index the ops consult.
        results (list[tuple[str, int]] | None): when given, collects the
            mount-relative (path, size) pair of each file found.
    """
    try:
        info = await stat(accessor, path, index)
    except FileNotFoundError:
        return 0
    prefix = mount_prefix_of(path.virtual, path.vfs_path)
    if info.type != FileType.DIRECTORY:
        size = info.size or 0
        if results is not None:
            results.append(("/" + mount_key(path.virtual, prefix), size))
        return size
    try:
        children = await readdir(accessor, path, index)
    except FileNotFoundError:
        return 0
    total = 0
    for child in children:
        trimmed = child.rstrip("/")
        child_spec = PathSpec(virtual=trimmed,
                              directory=trimmed,
                              resolved=False,
                              vfs_path=mount_key(trimmed, prefix))
        total += await walk(stat, readdir, accessor, child_spec, index,
                            results)
    return total


def make_walked_du(stat: StatOp, readdir: ReaddirOp) -> DuOps:
    """A native ``du`` that walks the backend's own readdir and stat.

    Args:
        stat (StatOp): the backend's stat.
        readdir (ReaddirOp): the backend's readdir.
    """

    async def size(accessor: Accessor,
                   path: PathSpec,
                   index: IndexCacheStore = NULL_INDEX) -> int:
        return await walk(stat, readdir, accessor, path, index, None)

    async def entries(accessor: Accessor,
                      path: PathSpec,
                      index: IndexCacheStore = NULL_INDEX) -> DuEntries:
        try:
            info = await stat(accessor, path, index)
        except FileNotFoundError:
            info = None
        if info is not None and info.type != FileType.DIRECTORY:
            return [], info.size or 0
        found: list[tuple[str, int]] = []
        total = await walk(stat, readdir, accessor, path, index, found)
        found.sort()
        return found, total

    return DuOps(size=size, entries=entries)
