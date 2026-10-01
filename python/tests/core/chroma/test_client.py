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

import pytest

from mirage.core.chroma import client
from mirage.core.chroma.client import fetch_path_tree, page_chunks


@pytest.mark.asyncio
async def test_fetch_path_tree(chroma_accessor):
    raw = await fetch_path_tree(chroma_accessor)
    assert "guides/quickstart" in raw


@pytest.mark.asyncio
async def test_fetch_path_tree_missing_raises(
    chroma_accessor, chroma_collection
):
    del chroma_collection.documents["__path_tree__"]
    chroma_collection.get = _empty_get
    with pytest.raises(FileNotFoundError):
        await fetch_path_tree(chroma_accessor)


async def _empty_get(**kwargs):
    return {"documents": []}


@pytest.mark.asyncio
async def test_page_chunks_reads_in_batches(
    monkeypatch, chroma_accessor, chroma_collection
):
    monkeypatch.setattr(client, "PAGE_CHUNK_BATCH_SIZE", 1)

    chunks = await page_chunks(chroma_accessor, "guides/quickstart")

    assert [chunk["document"] for chunk in chunks] == ["first", "second"]
    page_calls = [
        call
        for call in chroma_collection.get_calls
        if call.get("where") == {"page_slug": "guides/quickstart"}
    ]
    assert [call["limit"] for call in page_calls] == [1, 1, 1]
    assert [call["offset"] for call in page_calls] == [0, 1, 2]
