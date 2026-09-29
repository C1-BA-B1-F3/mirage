from mirage.accessor.chroma import ChromaAccessor
from mirage.commands.builtin.chroma.io import IO
from mirage.ops.registry import op
from mirage.types import PathSpec
from mirage.vfs.search import search_resources
from mirage.vfs.types import SearchQuery


@op("search", vfs="chroma")
async def search(
    accessor: ChromaAccessor,
    paths: list[PathSpec],
    query: str,
    *,
    index,
    **kwargs,
) -> bytes:
    explicit_prefix = kwargs.pop("mount_prefix", "")
    targets = paths or [
        PathSpec(virtual=explicit_prefix or "/",
                 directory=explicit_prefix or "/",
                 vfs_path="")
    ]
    return await search_resources(IO.search, accessor, targets,
                                  SearchQuery(query, options=kwargs), index)
