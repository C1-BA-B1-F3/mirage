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

from unittest.mock import patch

import aiohttp
import pytest

from mirage.cache.index import IndexEntry
from mirage.core.discord.readdir import _list_files, readdir
from mirage.core.hierarchy.readdir import DirListing
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.types import PathSpec
from tests.core.discord.conftest import BROKEN_DAY, DAY, SEALED_DAY
from tests.fixtures.index_spy import WindowSpy

pytestmark = pytest.mark.asyncio

CHANNEL = "My Server__G001/channels/general__C001"


def spec(virtual: str) -> PathSpec:
    return PathSpec(virtual=virtual,
                    directory=virtual,
                    vfs_path=virtual.lstrip("/"))


async def test_date_dir_contents_lists_chat_and_files(api, accessor, index):
    result = await readdir(accessor, spec(f"/{CHANNEL}/{DAY}"), index)
    assert result == [
        f"/{CHANNEL}/{DAY}/chat.jsonl",
        f"/{CHANNEL}/{DAY}/files",
    ]


async def test_files_dir_lists_attachments(api, accessor, index):
    result = await readdir(accessor, spec(f"/{CHANNEL}/{DAY}/files"), index)
    assert result == [f"/{CHANNEL}/{DAY}/files/kept__A1.txt"]


async def test_fetch_day_swallows_soft_errors(api, accessor, index):
    # A 403/404/429 seals an empty day rather than failing the listing.
    result = await readdir(accessor, spec(f"/{CHANNEL}/{SEALED_DAY}"), index)
    assert result == []


async def test_fetch_day_propagates_hard_errors(api, accessor, index):
    with pytest.raises(aiohttp.ClientResponseError):
        await readdir(accessor, spec(f"/{CHANNEL}/{BROKEN_DAY}"), index)


async def test_files_under_a_sealed_day_is_enoent(api, accessor, index):
    # The sealed day lists nothing, so its files subdir does not exist.
    with pytest.raises(FileNotFoundError):
        await readdir(accessor, spec(f"/{CHANNEL}/{SEALED_DAY}/files"), index)


def globbed(virtual: str, pattern: str) -> PathSpec:
    return PathSpec(virtual=f"{virtual}/{pattern}",
                    directory=f"{virtual}/",
                    vfs_path=f"{virtual.lstrip('/')}/{pattern}",
                    pattern=pattern)


async def test_channel_glob_reaches_days_outside_the_window(
        api, accessor, index):
    # The bare listing is the 30 days up to the newest message, so a glob
    # for an older month sees nothing unless it pushes its own span down.
    result = await readdir(accessor, globbed(f"/{CHANNEL}", "2023-11-*"),
                           index)
    assert result[0] == f"/{CHANNEL}/2023-11-01"
    assert result[-1] == f"/{CHANNEL}/2023-11-30"
    assert len(result) == 30


async def test_channel_glob_is_clipped_at_the_newest_message(
        api, accessor, index):
    # The fixture channel's last message is 2024-01-15, and nothing was
    # posted after it, so the rest of January is not listed.
    result = await readdir(accessor, globbed(f"/{CHANNEL}", "2024-01-*"),
                           index)
    assert result[-1] == f"/{CHANNEL}/2024-01-15"
    assert len(result) == 15


async def test_a_globbed_channel_listing_is_not_the_directory(
        api, accessor, index):
    # The glob's answer must not stand in for the channel: a later bare
    # listing still reports the recent window.
    await readdir(accessor, globbed(f"/{CHANNEL}", "2023-11-*"), index)
    result = await readdir(accessor, spec(f"/{CHANNEL}"), index)
    assert result[-1] == f"/{CHANNEL}/2024-01-15"
    assert len(result) == 30


async def test_a_channel_and_a_sealed_day_are_written_as_windows(
        api, accessor):
    # The channel lists the last 30 days, and a 403/404/429 seals an empty
    # day: neither is the backend saying anything outside it is gone.
    index = WindowSpy()
    await readdir(accessor, spec(f"/{CHANNEL}"), index)
    await readdir(accessor, spec(f"/{CHANNEL}/{SEALED_DAY}"), index)
    assert index.windows[f"/{CHANNEL}"] is True
    assert index.windows[f"/{CHANNEL}/{SEALED_DAY}"] is True


async def _soft_day_listing(_accessor, _channel_id, _day):
    return DirListing(entries=[], window=True)


async def test_a_soft_error_files_listing_is_a_window_too(accessor):
    # Reached when the files listing was evicted but the day survived; a
    # soft error there must not evict the attachments it listed before.
    own = IndexEntry(id="C001:2026-05-10",
                     name="files",
                     resource_type="discord/files",
                     vfs_name="files",
                     extra={"channel_id": "C001"})

    match = ScopeMatch(kind="files",
                       vfs_path=f"{CHANNEL}/2026-05-10/files",
                       slots={"day": "2026-05-10"})
    with patch("mirage.core.discord.readdir._day_listing",
               new=_soft_day_listing):
        listing = await _list_files(accessor, match, own)
    assert listing.window is True
