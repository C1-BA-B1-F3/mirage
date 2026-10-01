from datetime import datetime, timezone

from mirage.accessor.dify import DifyAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.dify.client import get_document_detail
from mirage.core.dify.tree import DIFY_TREE, extract_document_size
from mirage.core.slug_tree.stat import directory_stat
from mirage.types import ContentType, FileStat, FileType, JsonValue, PathSpec


async def stat_light(accessor: DifyAccessor,
                     path: PathSpec,
                     index: IndexCacheStore = NULL_INDEX) -> FileStat:
    resolved = await DIFY_TREE.resolve(accessor, path, index)
    if resolved.is_dir:
        return directory_stat(resolved)
    # size stays None: the entry size is the uploaded source file (e.g. the
    # original PDF), not the rendered segment text this mount serves
    # (FileStat.size must be render-derived or None, see the CLAUDE.md FUSE
    # rules). The source size remains in extra.
    extra = dict(resolved.entry.extra)
    if resolved.entry.size is not None:
        extra["source_size"] = resolved.entry.size
    return FileStat(
        name=resolved.entry.name,
        type=FileType.FILE,
        content=ContentType.TEXT,
        size=None,
        modified=timestamp_to_zulu(resolved.entry.remote_time),
        fingerprint=None,
        revision=None,
        extra=extra,
    )


async def stat(accessor: DifyAccessor,
               path: PathSpec,
               index: IndexCacheStore = NULL_INDEX) -> FileStat:
    resolved = await DIFY_TREE.resolve(accessor, path, index)
    if resolved.is_dir:
        return directory_stat(resolved)
    detail = await get_document_detail(accessor, resolved.entry.id)
    source_size = extract_document_size(detail)
    if source_size is None:
        source_size = resolved.entry.size
    extra = dict(resolved.entry.extra)
    extra["document_id"] = resolved.entry.id
    # size stays None: the API reports the uploaded source file's size (e.g.
    # the original PDF), not the rendered segment text this mount serves
    # (FileStat.size must be render-derived or None, see the CLAUDE.md FUSE
    # rules). The source size remains in extra.
    if source_size is not None:
        extra["source_size"] = source_size
    if "tokens" in detail:
        extra["tokens"] = detail.get("tokens")
    if "indexing_status" in detail:
        extra["indexing_status"] = detail.get("indexing_status")
    return FileStat(
        name=resolved.entry.name,
        type=FileType.FILE,
        content=ContentType.TEXT,
        size=None,
        modified=timestamp_to_zulu(detail.get("updated_at")),
        fingerprint=None,
        revision=None,
        extra=extra,
    )


def timestamp_to_zulu(value: JsonValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(
            value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)
