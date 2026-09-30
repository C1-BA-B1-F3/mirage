from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from mirage.cache.file.ram import RAMFileCacheStore
from mirage.cache.index.view import IndexView
from mirage.core.dify import readdir, tree
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key

from .conftest import list_basic_documents


@pytest.mark.asyncio
async def test_readdir_returns_directory_children(monkeypatch, dify_accessor,
                                                  dify_index, knowledge_root):
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)

    children = await readdir.readdir(dify_accessor, knowledge_root, dify_index)

    assert children == ["/knowledge/README.md", "/knowledge/guides"]


@pytest.mark.asyncio
async def test_readdir_rejects_files(monkeypatch, dify_accessor, dify_index,
                                     guide_path):
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)

    with pytest.raises(NotADirectoryError):
        await readdir.readdir(dify_accessor, guide_path, dify_index)


def _guides() -> PathSpec:
    return PathSpec.from_str_path("/knowledge/guides",
                                  mount_key("/knowledge/guides", "/knowledge"))


@pytest.mark.asyncio
async def test_an_expired_folder_under_a_live_root_refills(
        monkeypatch, dify_accessor, dify_index):
    # The tree is written whole, so an expired folder listing means the
    # tree aged out, not that the folder is gone: refill and answer.
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)
    await readdir.readdir(dify_accessor, _guides(), dify_index)
    await dify_index.set_dir("/knowledge/guides", [],
                             datetime.now(timezone.utc) - timedelta(seconds=1))
    assert await readdir.readdir(dify_accessor, _guides(), dify_index) == [
        "/knowledge/guides/quickstart"
    ]


@pytest.mark.asyncio
async def test_a_refused_folder_listing_refills_and_answers(
        monkeypatch, dify_accessor, dify_index):
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)

    async def refuse(_folder: str) -> bool:
        return False

    view = IndexView(dify_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    await readdir.readdir(dify_accessor, _guides(), view)
    assert await readdir.readdir(dify_accessor, _guides(),
                                 view) == ["/knowledge/guides/quickstart"]


@pytest.mark.asyncio
async def test_a_refused_root_listing_refills_and_answers(
        monkeypatch, dify_accessor, dify_index, knowledge_root):
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)

    async def refuse(_folder: str) -> bool:
        return False

    view = IndexView(dify_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    await readdir.readdir(dify_accessor, knowledge_root, view)
    assert await readdir.readdir(dify_accessor, knowledge_root, view) == [
        "/knowledge/README.md", "/knowledge/guides"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("root", [False, True])
async def test_refused_listing_fetches_tree_once(monkeypatch, dify_accessor,
                                                 dify_index, knowledge_root,
                                                 root):
    fetch = AsyncMock(wraps=list_basic_documents)
    monkeypatch.setattr(tree, "list_all_documents", fetch)
    decisions = []

    async def refuse(folder):
        decisions.append(folder)
        return False

    view = IndexView(dify_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    path = knowledge_root if root else _guides()
    for _ in range(2):
        fetch.reset_mock()
        assert await readdir.readdir(dify_accessor, path, view)
        assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_refilled_rows_respect_index_ownership(monkeypatch,
                                                     dify_accessor, dify_index,
                                                     knowledge_root):
    monkeypatch.setattr(tree, "list_all_documents", list_basic_documents)
    view = IndexView(dify_index, RAMFileCacheStore(), "/knowledge",
                     lambda key: not key.startswith("/knowledge/guides"))
    for _ in range(2):
        assert await readdir.readdir(dify_accessor, knowledge_root,
                                     view) == ["/knowledge/README.md"]
