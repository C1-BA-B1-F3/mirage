from mirage.accessor.dify import DifyAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore, LookupStatus
from mirage.core.dify.path import resolve_path
from mirage.core.dify.tree import refill_tree
from mirage.types import PathSpec
from mirage.utils.errors import enoent, enotdir


async def readdir(
    accessor: DifyAccessor,
    path: PathSpec,
    index: IndexCacheStore = NULL_INDEX,
) -> list[str]:
    resolved = await resolve_path(accessor, path, index)
    if not resolved.is_dir:
        raise enotdir(path)
    if resolved.children is not None:
        return resolved.children
    listing = await index.list_dir(resolved.virtual_key)
    if listing.entries is None and listing.status == LookupStatus.EXPIRED:
        refilled = await refill_tree(accessor, index, resolved.mount_prefix)
        if resolved.virtual_key in refilled:
            return refilled[resolved.virtual_key]
    if listing.entries is None:
        raise enoent(path)
    return listing.entries
