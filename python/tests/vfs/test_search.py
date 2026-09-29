import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mirage.accessor.base import Accessor
from mirage.types import PathSpec
from mirage.vfs.search import int_option, search_resources
from mirage.vfs.types import SearchOps, SearchQuery

PATH = PathSpec(virtual="/data", directory="/", vfs_path="")


@pytest.mark.asyncio
async def test_batch_query_is_ranked_once_and_receives_options():
    one = AsyncMock(side_effect=AssertionError("must use batch ranking"))
    batch = AsyncMock(return_value=["highest", "second"])
    capability = SearchOps(search=one, search_many=batch)
    accessor = Accessor()
    query = SearchQuery("question", options={"top_k": 2})
    assert await search_resources(capability, accessor, [PATH, PATH],
                                  query) == b"highest\nsecond\n"
    assert batch.await_count == 1
    assert batch.await_args.args[1:3] == ([PATH, PATH], query)
    one.assert_not_awaited()


@pytest.mark.asyncio
async def test_declined_batch_does_not_become_no_matches():
    capability = SearchOps(search=AsyncMock(),
                           search_many=AsyncMock(return_value=None))
    with pytest.raises(NotImplementedError, match="declined"):
        await search_resources(capability, Accessor(), [PATH],
                               SearchQuery("query"))


@pytest.mark.parametrize("value", [True, "10", None, 1.5])
def test_search_options_reject_non_integer_limits(value):
    with pytest.raises(ValueError, match="integer"):
        int_option(SearchQuery("query", options={"top_k": value}), "top_k", 10)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend,operation", [
    ("chroma", "search_segments"),
    ("dify", "search_segments"),
    ("qdrant", "search_rows_output"),
    ("lancedb", "search_rows_output"),
    ("mem0", "search_memories_rendered"),
])
async def test_builtin_semantic_adapters_delegate_one_batch(
        monkeypatch, backend, operation):
    module = importlib.import_module(f"mirage.core.{backend}.search")
    table = importlib.import_module(f"mirage.commands.builtin.{backend}.io").IO
    raw = AsyncMock(return_value=b"ranked record\n")
    monkeypatch.setattr(module, operation, raw)
    options = {"top_k": 2}
    if backend != "chroma":
        options.update({"method": "semantic", "threshold": 0.5})
    client = SimpleNamespace(
        config=SimpleNamespace(search_limit=10, default_search_limit=10))
    result = await search_resources(table.search, client, [PATH, PATH],
                                    SearchQuery("question", options=options))
    assert result == b"ranked record\n"
    raw.assert_awaited_once()
    assert raw.await_args.kwargs["top_k"] == 2
    assert raw.await_args.kwargs["mount_prefix"] == "/data"
    assert "grep" not in table.search.meta
