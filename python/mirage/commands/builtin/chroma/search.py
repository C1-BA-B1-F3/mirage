from mirage.accessor.chroma import ChromaAccessor
from mirage.commands.builtin.chroma.io import IO
from mirage.commands.builtin.utils.paths import default_paths
from mirage.commands.config import CommandOpts
from mirage.commands.registry import command
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec
from mirage.vfs.search import search_resources
from mirage.vfs.types import SearchQuery


@command("chroma-query", vfs="chroma", spec=SPECS["search"])
async def search(
    accessor: ChromaAccessor,
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(opts.flags, spec=SPECS["search"])
    if not texts:
        raise ValueError("search: query is required")
    query = texts[0]
    top_k = fl.as_int("top_k")
    target_paths = default_paths(paths, opts.cwd)
    output = await search_resources(
        IO.search, accessor, target_paths,
        SearchQuery(query,
                    options={"top_k": top_k if top_k is not None else 10}),
        opts.index)
    return output, IOResult()
