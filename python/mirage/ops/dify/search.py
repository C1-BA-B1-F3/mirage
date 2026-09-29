from mirage.accessor.dify import DifyAccessor
from mirage.commands.builtin.dify.io import IO
from mirage.ops.registry import op
from mirage.types import PathSpec
from mirage.vfs.search import search_resources
from mirage.vfs.types import SearchQuery


@op("search", vfs="dify")
async def search(
    accessor: DifyAccessor,
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
