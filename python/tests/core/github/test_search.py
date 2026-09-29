# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from unittest.mock import AsyncMock, patch

import pytest

from mirage.accessor.github import GitHubAccessor
from mirage.core.api.client import ApiResponse
from mirage.core.github.config import GhConfig, GitHubConfig
from mirage.core.github.search import (SearchResult, narrow_paths, search,
                                       search_code)
from mirage.core.github.tree_entry import TreeEntry
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key


@pytest.fixture
def config():
    return GitHubConfig(token="ghp_test")


def _item(path: str, full_name: str | int | None) -> dict:
    return {"path": path, "sha": path, "repository": {"full_name": full_name}}


def _body(items: list[dict], total: int | None = None) -> dict:
    return {
        "total_count": len(items) if total is None else total,
        "incomplete_results": False,
        "items": items,
    }


def _blob(path: str, size: int | None) -> TreeEntry:
    return TreeEntry(path=path, type="blob", sha=path, size=size)


# GitHub's documented code-search limit; files at or over it are not indexed.
SEARCH_LIMIT = 384 * 1024

_SMALL_TREE = {"src/a.py": _blob("src/a.py", 10)}


def _accessor(config: GitHubConfig, tree: dict[str,
                                               TreeEntry]) -> GitHubAccessor:
    return GitHubAccessor(config, "acme", "proj", "main", "main", tree=tree)


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_basic(mock_get, config):
    mock_get.return_value = _body([
        _item("src/main.py", "acme/proj") | {
            "sha": "aaa"
        },
        _item("src/utils.py", "acme/proj") | {
            "sha": "bbb"
        },
    ])
    result, truncated = await search_code(config, "acme", "proj", "import os")
    assert len(result) == 2
    assert result[0] == SearchResult(path="src/main.py", sha="aaa")
    assert truncated is False
    mock_get.assert_awaited_once_with(config.token,
                                      "/search/code",
                                      params={
                                          "q": "import os repo:acme/proj",
                                          "per_page": "100"
                                      },
                                      base_url=None,
                                      session=None)


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_empty_results(mock_get, config):
    mock_get.return_value = _body([])
    result = await search_code(config, "acme", "proj", "nonexistent")
    assert result == ([], False)


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_with_path_filter(mock_get, config):
    mock_get.return_value = _body([_item("src/main.py", "acme/proj")])
    await search_code(config, "acme", "proj", "import os", path_filter="src/")
    mock_get.assert_awaited_once_with(config.token,
                                      "/search/code",
                                      params={
                                          "q":
                                          "import os repo:acme/proj path:src/",
                                          "per_page": "100"
                                      },
                                      base_url=None,
                                      session=None)


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_strips_leading_slash_in_filter(
        mock_search, config):
    mock_search.return_value = ([SearchResult(path="src/main.py",
                                              sha="aaa")], False)
    paths = [PathSpec(vfs_path="src", virtual="/src", directory="/src")]
    await narrow_paths(_accessor(config, _SMALL_TREE), "import", paths)
    _, kwargs = mock_search.await_args
    assert kwargs["path_filter"] == "src"


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_root_uses_no_filter(mock_search, config):
    mock_search.return_value = ([SearchResult(path="src/main.py",
                                              sha="aaa")], False)
    paths = [PathSpec(vfs_path="", virtual="/", directory="/")]
    await narrow_paths(_accessor(config, _SMALL_TREE), "import", paths)
    _, kwargs = mock_search.await_args
    assert kwargs["path_filter"] is None


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_normalizes_results_with_leading_slash(
        mock_search, config):
    mock_search.return_value = ([
        SearchResult(path="src/main.py", sha="aaa"),
        SearchResult(path="src/utils.py", sha="bbb"),
    ], False)
    paths = [
        PathSpec(vfs_path=mount_key("/gh", "/gh"),
                 virtual="/gh",
                 directory="/gh")
    ]
    out = await narrow_paths(_accessor(config, _SMALL_TREE), "import", paths)
    assert [p.virtual for p in out] == ["/gh/src/main.py", "/gh/src/utils.py"]
    assert [p.vfs_path for p in out] == ["src/main.py", "src/utils.py"]


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_voids_the_narrowing_on_error(
        mock_search, config, caplog):
    mock_search.side_effect = RuntimeError("boom")
    paths = [PathSpec(vfs_path="src", virtual="/src", directory="/src")]
    with caplog.at_level("WARNING"):
        out = await narrow_paths(_accessor(config, _SMALL_TREE), "import",
                                 paths)
    assert out is None
    assert "falling back to per-file scan" in caplog.text


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_narrow_paths_forwards_the_session_pool(mock_get, config):
    # The mount's grep push-down passes its accessor pool; a search that
    # dropped it opened an aiohttp session per code-search request.
    mock_get.return_value = _body([])
    accessor = _accessor(config, {})
    await narrow_paths(accessor, "needle", [PathSpec.from_str_path("/")])
    assert mock_get.await_args.kwargs["session"] is accessor.pool


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_asks_for_the_largest_page(mock_get, config):
    # The default page is 30 rows, and a first page read as the whole answer
    # silently narrows grep to 30 files.
    mock_get.return_value = _body([])
    await search_code(config, "acme", "proj", "needle")
    assert mock_get.await_args.kwargs["params"]["per_page"] == "100"


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_keeps_only_the_mounted_repository(mock_get, config):
    # The pattern is sent verbatim, so a qualifier inside it can rescope the
    # search; a fork shares the repository name and a prefix is not a match.
    mock_get.return_value = _body([
        _item("src/a.py", "acme/proj"),
        _item("src/a.py", "other/x"),
        _item("src/a.py", "other/proj"),
        _item("src/a.py", "acme/other"),
        _item("src/a.py", "acme/proj-fork"),
    ])
    results, _ = await search_code(config, "acme", "proj", "needle")
    assert results == [SearchResult(path="src/a.py", sha="src/a.py")]


@pytest.mark.asyncio
@pytest.mark.parametrize("full_name, owner, repo", [
    ("Acme/Proj", "acme", "proj"),
    ("acme/proj", "Acme", "Proj"),
])
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_compares_the_repository_case_insensitively(
        mock_get, full_name, owner, repo, config):
    mock_get.return_value = _body([_item("src/a.py", full_name)])
    results, _ = await search_code(config, owner, repo, "needle")
    assert [r.path for r in results] == ["src/a.py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("item", [
    {
        "path": "src/a.py",
        "sha": "x"
    },
    {
        "path": "src/a.py",
        "sha": "x",
        "repository": None
    },
    {
        "path": "src/a.py",
        "sha": "x",
        "repository": {}
    },
    _item("src/a.py", None),
    _item("src/a.py", 123),
])
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_drops_an_item_that_names_no_repository(
        mock_get, item, config):
    # Nothing vouches for such an item, and dropping it must not raise: a
    # raise inside narrow_paths voids the whole narrowing.
    mock_get.return_value = _body([item])
    results, _ = await search_code(config, "acme", "proj", "needle")
    assert results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body, truncated", [
    ({
        "total_count": 1,
        "incomplete_results": False
    }, False),
    ({
        "total_count": 0,
        "incomplete_results": False
    }, False),
    ({
        "total_count": 2,
        "incomplete_results": False
    }, True),
    ({
        "total_count": 1,
        "incomplete_results": True
    }, True),
    ({
        "incomplete_results": False
    }, True),
    ({
        "total_count": "1",
        "incomplete_results": False
    }, True),
    ({
        "total_count": True,
        "incomplete_results": False
    }, True),
    ({
        "total_count": 0.5,
        "incomplete_results": False
    }, True),
    ({
        "total_count": 1
    }, True),
])
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_reports_an_answer_that_is_not_the_whole_set(
        mock_get, body, truncated, config):
    # Only an answer that says it is complete, with a count no larger than
    # the rows it carries, is the whole set; anything else is truncated.
    mock_get.return_value = {**body, "items": [_item("src/a.py", "acme/proj")]}
    _, got = await search_code(config, "acme", "proj", "needle")
    assert got is truncated


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_reads_null_items_as_no_rows(mock_get, config):
    mock_get.return_value = {
        "total_count": 0,
        "incomplete_results": False,
        "items": None
    }
    assert await search_code(config, "acme", "proj", "needle") == ([], False)


@pytest.mark.asyncio
@patch("mirage.core.github.search.github_get", new_callable=AsyncMock)
async def test_search_code_judges_completeness_before_filtering(
        mock_get, config):
    # total_count counts every row the search matched, foreign ones too.
    mock_get.return_value = _body(
        [_item("src/a.py", "acme/proj"),
         _item("src/b.py", "other/x")])
    results, truncated = await search_code(config, "acme", "proj", "needle")
    assert [r.path for r in results] == ["src/a.py"]
    assert truncated is False


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_truncated_answer_returns_none(mock_search, config):
    mock_search.return_value = ([SearchResult(path="src/a.py", sha="a")], True)
    out = await narrow_paths(_accessor(config, _SMALL_TREE), "needle",
                             [PathSpec.from_str_path("/")])
    assert out is None


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_stops_at_the_first_truncated_scope(
        mock_search, config):
    # Code search is rate limited; a narrowing already void asks nothing more.
    mock_search.return_value = ([], True)
    scopes = [
        PathSpec(vfs_path="src", virtual="/src", directory="/src"),
        PathSpec(vfs_path="docs", virtual="/docs", directory="/docs"),
    ]
    out = await narrow_paths(_accessor(config, _SMALL_TREE), "needle", scopes)
    assert out is None
    assert mock_search.await_count == 1


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_a_failed_scope_voids_the_others(
        mock_search, config):
    # A scope whose search failed contributes nothing, so the hits of the
    # scopes that did answer are not the whole set either.
    mock_search.side_effect = [
        ([SearchResult(path="src/a.py", sha="a")], False),
        RuntimeError("boom"),
    ]
    scopes = [
        PathSpec(vfs_path="src", virtual="/src", directory="/src"),
        PathSpec(vfs_path="docs", virtual="/docs", directory="/docs"),
    ]
    out = await narrow_paths(_accessor(config, _SMALL_TREE), "needle", scopes)
    assert out is None


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_adds_the_files_search_never_indexes(
        mock_search, config):
    # Code search skips files at or over the limit, so a
    # trusted narrowing has to read them itself; one that is also a hit is
    # listed once.
    tree = {
        "src/a.py": _blob("src/a.py", 10),
        "src/big.bin": _blob("src/big.bin", SEARCH_LIMIT),
    }
    for hits in (["src/a.py"], ["src/a.py", "src/big.bin"]):
        mock_search.return_value = ([
            SearchResult(path=h, sha=h) for h in hits
        ], False)
        out = await narrow_paths(_accessor(config, tree), "needle",
                                 [PathSpec.from_str_path("/")])
        assert out is not None
        assert [p.virtual for p in out] == ["/src/a.py", "/src/big.bin"]


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_adds_big_files_only_from_the_scope(
        mock_search, config):
    # A big file elsewhere would put lines from outside the operand in the
    # output.
    tree = {
        "src/a.py": _blob("src/a.py", 10),
        "src/big.bin": _blob("src/big.bin", SEARCH_LIMIT),
        "docs/big.md": _blob("docs/big.md", SEARCH_LIMIT),
    }
    mock_search.return_value = ([SearchResult(path="src/a.py",
                                              sha="a")], False)
    out = await narrow_paths(
        _accessor(config, tree), "needle",
        [PathSpec(vfs_path="src", virtual="/src", directory="/src")])
    assert out is not None
    assert [p.virtual for p in out] == ["/src/a.py", "/src/big.bin"]


@pytest.mark.asyncio
@patch("mirage.core.github.search.search_code", new_callable=AsyncMock)
async def test_narrow_paths_big_files_do_not_rescue_a_truncated_answer(
        mock_search, config):
    mock_search.return_value = ([], True)
    tree = {"src/big.bin": _blob("src/big.bin", SEARCH_LIMIT)}
    out = await narrow_paths(_accessor(config, tree), "needle",
                             [PathSpec.from_str_path("/")])
    assert out is None


@pytest.mark.asyncio
async def test_rest_search_paginates_and_clips_the_final_page(monkeypatch):
    requests = []

    async def request(*args, **kwargs):
        params = kwargs["params"]
        requests.append(dict(params))
        start = (int(params["page"]) - 1) * 100
        return ApiResponse(
            {"items": list(range(start, start + 100))}, 200,
            {"link": '<https://api.github.test/next>; rel="next"'})

    monkeypatch.setitem(search.__globals__, "github_request_response", request)
    rows = await search(GhConfig(token="test"), "issues", "repo:acme/proj",
                        102, "created", "asc")
    assert rows == list(range(102))
    assert [params["page"] for params in requests] == ["1", "2"]
    assert all(params["per_page"] == "100" for params in requests)
    assert requests[0]["sort"] == "created"
    assert requests[0]["order"] == "asc"
