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
from aiohttp import ClientResponseError
from fakeredis.aioredis import FakeRedis

from mirage.cache.index import IndexEntry
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.redis import RedisIndexCacheStore
from mirage.core.google.entry import resolve_app_entry
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.types import PathSpec
from mirage.vfs.gdocs.doc_entry import make_filename

ITEM = {
    "id": "doc1",
    "name": "Notes",
    "mimeType": "application/vnd.google-apps.document",
    "modifiedTime": "2026-04-01T12:00:00Z",
    "owners": [{
        "me": True
    }],
    "size": "1000"
}
NAME = make_filename(ITEM["name"], ITEM["id"], ITEM["modifiedTime"])
PATH = PathSpec(directory="/docs/owned/" + NAME,
                virtual="/docs/owned/" + NAME,
                vfs_path="owned/" + NAME)
MATCH = ScopeMatch(kind="file",
                   vfs_path=PATH.vfs_path,
                   slots={
                       "corpus": "owned",
                       "file_id": "doc1"
                   })


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["ram", "redis"])
@pytest.mark.parametrize("outcome", [
    "updated", "renamed", "date", "trashed", "mime", "owner", "deleted",
    "forbidden", "unavailable"
])
async def test_direct_lookup_after_incomplete_search(backend, outcome):
    client = FakeRedis() if backend == "redis" else None
    index = RAMIndexCacheStore() if client is None else RedisIndexCacheStore(
        client=client)
    retained = IndexEntry(id="doc1",
                          name="Notes",
                          vfs_name=NAME,
                          resource_type="gdocs/file",
                          remote_time="old")
    await index.put(PATH.virtual, retained)
    await index.invalidate()
    item = dict(ITEM)
    error = None
    if outcome == "renamed":
        item["name"] = "Renamed"
    if outcome == "date":
        item["modifiedTime"] = "2026-04-02T12:00:00Z"
    if outcome == "trashed":
        item["trashed"] = True
    if outcome == "mime":
        item["mimeType"] = "text/plain"
    if outcome == "owner":
        item["owners"] = []
    if outcome in ("deleted", "forbidden", "unavailable"):
        error = ClientResponseError(None, (),
                                    status={
                                        "deleted": 404,
                                        "forbidden": 403,
                                        "unavailable": 503
                                    }[outcome])
    try:
        with patch("mirage.core.google.entry.get_file",
                   new_callable=AsyncMock,
                   return_value=item,
                   side_effect=error) as get, patch(
                       "mirage.core.google.drive.list_all_files",
                       new_callable=AsyncMock,
                       side_effect=AssertionError("must not search")):
            if outcome == "updated":
                entry = await resolve_app_entry(None, MATCH, PATH, index,
                                                ITEM["mimeType"], "gdocs/file",
                                                make_filename)
                assert entry.remote_time == ITEM["modifiedTime"]
                assert entry.size is None
                assert entry.extra == {"source_size": 1000}
            elif outcome in ("forbidden", "unavailable"):
                with pytest.raises(ClientResponseError) as raised:
                    await resolve_app_entry(None, MATCH, PATH, index,
                                            ITEM["mimeType"], "gdocs/file",
                                            make_filename)
                assert raised.value is error
                assert (await index.get(PATH.virtual)).entry is not None
            else:
                with pytest.raises(FileNotFoundError):
                    await resolve_app_entry(None, MATCH, PATH, index,
                                            ITEM["mimeType"], "gdocs/file",
                                            make_filename)
                assert (await index.get(PATH.virtual)).entry is None
            get.assert_awaited_once_with(None, "doc1")
    finally:
        await index.close()
        if client is not None:
            await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["ram", "redis"])
@pytest.mark.parametrize("listing", ["complete", "partial", "expired"])
async def test_only_complete_live_listing_proves_absence(backend, listing):
    client = FakeRedis() if backend == "redis" else None
    index = RAMIndexCacheStore() if client is None else RedisIndexCacheStore(
        client=client)
    try:
        if listing == "partial":
            await index.set_partial_dir("/docs/owned", [])
        else:
            await index.set_dir("/docs/owned", [])
        if listing == "expired":
            await index.invalidate()
        with patch("mirage.core.google.entry.get_file",
                   new_callable=AsyncMock,
                   return_value=ITEM) as get:
            if listing == "complete":
                with pytest.raises(FileNotFoundError):
                    await resolve_app_entry(None, MATCH, PATH, index,
                                            ITEM["mimeType"], "gdocs/file",
                                            make_filename)
                get.assert_not_awaited()
            else:
                entry = await resolve_app_entry(None, MATCH, PATH, index,
                                                ITEM["mimeType"], "gdocs/file",
                                                make_filename)
                assert entry.id == ITEM["id"]
                get.assert_awaited_once_with(None, "doc1")
    finally:
        await index.close()
        if client is not None:
            await client.aclose()
