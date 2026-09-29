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

import pytest

from mirage.core.box.resolve import (mount_relative_key, resolve_chain,
                                     resolve_item)

FOLDERS = {
    "0": [{
        "type": "folder",
        "id": "10",
        "name": "team"
    }, {
        "type": "file",
        "id": "2",
        "name": "a.txt"
    }],
    "10": [{
        "type": "folder",
        "id": "11",
        "name": "docs"
    }],
    "11": [],
}


async def _list(tm, folder_id: str) -> list[dict]:
    return FOLDERS[folder_id]


@pytest.mark.asyncio
async def test_resolve_chain_stops_at_the_first_missing_component(accessor):
    with patch("mirage.core.box.resolve.list_folder_items", _list):
        chain = await resolve_chain(accessor, ["team", "gone", "x"])
    assert [c["id"] for c in chain] == ["10"]


@pytest.mark.asyncio
async def test_resolve_chain_never_lists_a_file(accessor):
    listed: list[str] = []

    async def spy(tm, folder_id: str) -> list[dict]:
        listed.append(folder_id)
        return FOLDERS[folder_id]

    with patch("mirage.core.box.resolve.list_folder_items", spy):
        chain = await resolve_chain(accessor, ["a.txt", "x"])
    assert [c["id"] for c in chain] == ["2"]
    assert listed == ["0"]


@pytest.mark.asyncio
async def test_resolve_item_answers_only_for_the_whole_path(accessor):
    with patch("mirage.core.box.resolve.list_folder_items", _list):
        assert (await resolve_item(accessor, ["team", "docs"]))["id"] == "11"
        assert (await resolve_item(accessor, ["a.txt"]))["id"] == "2"
        assert await resolve_item(accessor, ["team", "gone"]) is None
        assert await resolve_item(accessor, ["a.txt", "x"]) is None
        assert await resolve_item(accessor, []) is None


def test_mount_relative_key_trims_through_the_mount_root():
    item = {
        "name": "a.txt",
        "path_collection": {
            "entries": [{
                "id": "0",
                "name": "All Files"
            }, {
                "id": "10",
                "name": "team"
            }, {
                "id": "11",
                "name": "docs"
            }]
        },
    }
    assert mount_relative_key(item, "0") == "team/docs/a.txt"
    assert mount_relative_key(item, "10") == "docs/a.txt"
    assert mount_relative_key(item, "99") is None
