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

from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.airtable.read import read
from mirage.core.airtable.stat import stat
from mirage.types import ContentType, FileType, PathSpec
from mirage.utils.key_prefix import mount_key
from tests.fixtures.airtable_api import make_accessor

ROOT = "/at"
BASE = f"{ROOT}/bases/Product_Roadmap__appRoadmapBase001"
TABLE = f"{BASE}/Features__tblFeatures000001"


def _spec(virtual: str) -> PathSpec:
    return PathSpec(virtual=virtual,
                    directory=virtual.rsplit("/", 1)[0],
                    vfs_path=mount_key(virtual, ROOT))


@pytest.mark.asyncio
async def test_json_leaves_stat_at_their_rendered_size(airtable_api):
    accessor = make_accessor()
    index = RAMIndexCacheStore()
    for leaf in (f"{BASE}/base.json", f"{TABLE}/table.json"):
        info = await stat(accessor, _spec(leaf), index)
        body = await read(accessor, _spec(leaf), index)
        assert info.type == FileType.FILE
        assert info.content == ContentType.JSON
        assert info.size == len(body)


@pytest.mark.asyncio
async def test_record_files_are_size_unknown(airtable_api):
    accessor = make_accessor()
    index = RAMIndexCacheStore()
    records = await stat(accessor, _spec(f"{TABLE}/records.jsonl"), index)
    view = await stat(
        accessor,
        _spec(f"{TABLE}/views/Done_shipped__viwDone0000000001.jsonl"), index)
    assert records.size is None and view.size is None
    assert view.extra == {"view_id": "viwDone0000000001"}


@pytest.mark.asyncio
async def test_directories_stat_as_directories(airtable_api):
    accessor = make_accessor()
    index = RAMIndexCacheStore()
    for path in (f"{ROOT}/bases", BASE, TABLE, f"{TABLE}/views"):
        assert (await stat(accessor, _spec(path),
                           index)).type == FileType.DIRECTORY


@pytest.mark.asyncio
async def test_an_unlisted_view_is_enoent(airtable_api):
    with pytest.raises(FileNotFoundError):
        await stat(make_accessor(),
                   _spec(f"{TABLE}/views/Gone__viwGone0000000001.jsonl"),
                   RAMIndexCacheStore())
