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

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from mirage.cache.file.ram import RAMFileCacheStore
from mirage.cache.index.view import IndexView
from mirage.core.chroma import tree
from mirage.core.chroma.readdir import readdir
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key


@pytest.mark.asyncio
async def test_readdir_root_lists_top_level(chroma_accessor, chroma_index,
                                            knowledge_root):
    entries = await readdir(chroma_accessor, knowledge_root, chroma_index)
    assert sorted(entries) == ["/knowledge/api", "/knowledge/guides"]


@pytest.mark.asyncio
async def test_readdir_subdir(chroma_accessor, chroma_index):
    path = PathSpec.from_str_path("/knowledge/guides",
                                  mount_key("/knowledge/guides", "/knowledge"))
    entries = await readdir(chroma_accessor, path, chroma_index)
    assert entries == ["/knowledge/guides/quickstart"]


@pytest.mark.asyncio
async def test_readdir_on_file_raises(chroma_accessor, chroma_index,
                                      quickstart_path):
    with pytest.raises(NotADirectoryError):
        await readdir(chroma_accessor, quickstart_path, chroma_index)


def _guides() -> PathSpec:
    return PathSpec.from_str_path("/knowledge/guides",
                                  mount_key("/knowledge/guides", "/knowledge"))


@pytest.mark.asyncio
async def test_an_expired_folder_under_a_live_root_refills(
        chroma_accessor, chroma_index):
    # The tree is written whole, so an expired folder listing means the
    # tree aged out, not that the folder is gone: refill and answer.
    await readdir(chroma_accessor, _guides(), chroma_index)
    await chroma_index.set_dir(
        "/knowledge/guides", [],
        datetime.now(timezone.utc) - timedelta(seconds=1))
    entries = await readdir(chroma_accessor, _guides(), chroma_index)
    assert entries == ["/knowledge/guides/quickstart"]


@pytest.mark.asyncio
async def test_a_refused_folder_listing_refills_and_answers(
        chroma_accessor, chroma_index):
    # A read outside any command under fresh has every cached listing
    # refused; answering ENOENT would fail every such ls of a subfolder.
    async def refuse(_folder: str) -> bool:
        return False

    view = IndexView(chroma_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    await readdir(chroma_accessor, _guides(), view)
    assert await readdir(chroma_accessor, _guides(),
                         view) == ["/knowledge/guides/quickstart"]


@pytest.mark.asyncio
async def test_a_folder_the_tree_lacks_is_still_enoent(chroma_accessor,
                                                       chroma_index):
    path = PathSpec.from_str_path("/knowledge/nope",
                                  mount_key("/knowledge/nope", "/knowledge"))
    with pytest.raises(FileNotFoundError):
        await readdir(chroma_accessor, path, chroma_index)


@pytest.mark.asyncio
async def test_a_refused_root_listing_refills_and_answers(
        chroma_accessor, chroma_index, knowledge_root):

    async def refuse(_folder: str) -> bool:
        return False

    view = IndexView(chroma_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    await readdir(chroma_accessor, knowledge_root, view)
    assert sorted(await
                  readdir(chroma_accessor, knowledge_root,
                          view)) == ["/knowledge/api", "/knowledge/guides"]


@pytest.mark.asyncio
@pytest.mark.parametrize("root", [False, True])
async def test_refused_listing_fetches_tree_once(monkeypatch, chroma_accessor,
                                                 chroma_index, knowledge_root,
                                                 root):
    fetch = AsyncMock(wraps=tree.fetch_path_tree)
    monkeypatch.setattr(tree, "fetch_path_tree", fetch)
    decisions = []

    async def refuse(folder):
        decisions.append(folder)
        return False

    view = IndexView(chroma_index,
                     RAMFileCacheStore(),
                     "/knowledge",
                     lambda _key: True,
                     may_serve_listing=refuse)
    path = knowledge_root if root else _guides()
    for _ in range(2):
        fetch.reset_mock()
        assert await readdir(chroma_accessor, path, view)
        assert fetch.await_count == 1
