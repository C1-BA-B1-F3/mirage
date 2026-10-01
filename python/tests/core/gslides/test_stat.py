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

from mirage.accessor.gslides import GSlidesAccessor
from mirage.cache.index import IndexEntry
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.gslides.stat import stat
from mirage.types import ContentType, FileType, PathSpec
from mirage.utils.key_prefix import mount_key


@pytest.fixture
def accessor():
    return GSlidesAccessor(config=None, token_manager=None)


@pytest.fixture
def index():
    return RAMIndexCacheStore()


@pytest.mark.asyncio
async def test_stat_root(accessor, index):
    result = await stat(
        accessor,
        PathSpec(
            vfs_path=mount_key("/gslides", "/gslides"),
            virtual="/gslides",
            directory="/gslides",
        ),
        index,
    )
    assert result.type == FileType.DIRECTORY
    assert result.name == "/"


@pytest.mark.asyncio
async def test_stat_owned_dir(accessor, index):
    result = await stat(
        accessor,
        PathSpec(
            vfs_path=mount_key("/gslides/owned", "/gslides"),
            virtual="/gslides/owned",
            directory="/gslides/owned",
        ),
        index,
    )
    assert result.type == FileType.DIRECTORY
    assert result.name == "owned"


@pytest.mark.asyncio
async def test_stat_deck_from_cache(accessor, index):
    await index.set_dir(
        "/gslides/owned",
        [
            (
                "2026-04-01_My_Deck__d1.gslide.json",
                IndexEntry(
                    id="d1",
                    name="My Deck",
                    resource_type="gslides/file",
                    remote_time="2026-04-01T00:00:00.000Z",
                    vfs_name="2026-04-01_My_Deck__d1.gslide.json",
                    size=2048,
                ),
            ),
        ],
    )
    target = "/gslides/owned/2026-04-01_My_Deck__d1.gslide.json"
    result = await stat(
        accessor,
        PathSpec(
            vfs_path=mount_key(target, "/gslides"),
            virtual=target,
            directory=target,
        ),
        index,
    )
    assert result.content == ContentType.JSON
    assert result.extra["doc_id"] == "d1"
    assert result.size == 2048
    assert result.fingerprint == "2026-04-01T00:00:00.000Z"


@pytest.mark.asyncio
async def test_stat_cache_miss_fetches_metadata_by_id(accessor, index):
    files = [
        {
            "mimeType": "application/vnd.google-apps.presentation",
            "id": "d1",
            "name": "My Deck",
            "modifiedTime": "2026-04-01T00:00:00.000Z",
            "size": "2048",
            "owners": [{"me": True}],
        }
    ]
    target = "/gslides/owned/2026-04-01_My_Deck__d1.gslide.json"
    with patch(
        "mirage.core.google.entry.get_file",
        new_callable=AsyncMock,
        return_value=files[0],
    ) as mock_list:
        result = await stat(
            accessor,
            PathSpec(
                vfs_path=mount_key(target, "/gslides"),
                virtual=target,
                directory=target,
            ),
            index,
        )
    assert result.content == ContentType.JSON
    assert result.extra["doc_id"] == "d1"
    assert mock_list.call_count == 1


@pytest.mark.asyncio
async def test_stat_not_found_after_fallback(accessor, index):
    files = [
        {
            "mimeType": "application/vnd.google-apps.presentation",
            "id": "d1",
            "name": "Other",
            "modifiedTime": "2026-04-01T00:00:00.000Z",
            "owners": [{"me": True}],
        }
    ]
    with patch(
        "mirage.core.google.entry.get_file",
        new_callable=AsyncMock,
        return_value=files[0],
    ):
        with pytest.raises(FileNotFoundError):
            await stat(
                accessor,
                PathSpec(
                    vfs_path=mount_key(
                        "/gslides/owned/nope.gslide.json", "/gslides"
                    ),
                    virtual="/gslides/owned/nope.gslide.json",
                    directory="/gslides/owned/nope.gslide.json",
                ),
                index,
            )
