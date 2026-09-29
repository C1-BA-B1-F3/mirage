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

from unittest.mock import AsyncMock

import pytest

from mirage.accessor.mongodb import MongoDBAccessor
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.commands.builtin.mongodb.wc import wc
from mirage.commands.config import CommandOpts
from mirage.io.stream import materialize
from mirage.types import PathSpec
from mirage.vfs.mongodb.config import MongoDBConfig


def _path(s: str) -> PathSpec:
    return PathSpec(virtual=s, directory=s, vfs_path=s.strip("/"))


@pytest.mark.asyncio
async def test_wc_l_does_not_count_a_collection_it_cannot_see(monkeypatch):
    """``count_documents`` answers 0 for a collection that does not exist
    and for one outside ``databases``, so ``wc -l`` printed a zero count
    for a file ``ls`` and ``cat`` said was not there."""
    monkeypatch.setattr("mirage.core.mongodb.readdir.entity_exists",
                        AsyncMock(return_value=False))
    count = AsyncMock(side_effect=AssertionError("counted the collection"))
    monkeypatch.setitem(wc.__wrapped__.__globals__, "count_documents", count)
    accessor = MongoDBAccessor(config=MongoDBConfig(
        uri="mongodb://localhost:27017"))
    out, io = await wc(
        accessor, [_path("/db1/collections/missing/documents.jsonl")], [],
        CommandOpts(index=RAMIndexCacheStore(), flags={"lines": True}))
    await materialize(out)
    assert io.exit_code == 1
    assert b"No such file or directory" in await materialize(io.stderr)
    count.assert_not_awaited()


@pytest.mark.asyncio
async def test_wc_l_counts_a_visible_collection_server_side(monkeypatch):
    monkeypatch.setattr("mirage.core.mongodb.readdir.entity_exists",
                        AsyncMock(return_value=True))
    monkeypatch.setitem(wc.__wrapped__.__globals__, "count_documents",
                        AsyncMock(return_value=7))
    accessor = MongoDBAccessor(config=MongoDBConfig(
        uri="mongodb://localhost:27017"))
    path = "/db1/collections/coll1/documents.jsonl"
    out, io = await wc(
        accessor, [_path(path)], [],
        CommandOpts(index=RAMIndexCacheStore(), flags={"lines": True}))
    assert await materialize(out) == f"7 {path}\n".encode()
    assert io.exit_code == 0
