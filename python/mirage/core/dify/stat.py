from mirage.accessor.dify import DifyAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.dify.client import get_document_detail
from mirage.core.dify.tree import DIFY_TREE, epoch_text, extract_document_size
from mirage.core.slug_tree.stat import directory_stat
from mirage.types import ContentType, FileStat, FileType, PathSpec


async def stat_light(accessor: DifyAccessor,
                     path: PathSpec,
                     index: IndexCacheStore = NULL_INDEX) -> FileStat:
    resolved = await DIFY_TREE.resolve(accessor, path, index)
    if resolved.is_dir:
        return directory_stat(resolved)
    return FileStat(
        name=resolved.entry.name,
        type=FileType.FILE,
        content=ContentType.TEXT,
        size=None,
        modified=resolved.entry.remote_time or None,
        birthtime=resolved.entry.remote_time or None,
        fingerprint=None,
        revision=None,
        extra=dict(resolved.entry.extra),
    )


async def stat(accessor: DifyAccessor,
               path: PathSpec,
               index: IndexCacheStore = NULL_INDEX) -> FileStat:
    resolved = await DIFY_TREE.resolve(accessor, path, index)
    if resolved.is_dir:
        return directory_stat(resolved)
    detail = await get_document_detail(accessor, resolved.entry.id)
    extra = dict(resolved.entry.extra)
    extra["document_id"] = resolved.entry.id
    source_size = extract_document_size(detail)
    if source_size is not None:
        extra["source_size"] = source_size
    if "tokens" in detail:
        extra["tokens"] = detail.get("tokens")
    if "indexing_status" in detail:
        extra["indexing_status"] = detail.get("indexing_status")
    created = (epoch_text(detail.get("created_at"))
               or resolved.entry.remote_time or None)
    return FileStat(
        name=resolved.entry.name,
        type=FileType.FILE,
        content=ContentType.TEXT,
        size=None,
        modified=epoch_text(detail.get("updated_at")) or created,
        birthtime=created,
        fingerprint=None,
        revision=None,
        extra=extra,
    )
