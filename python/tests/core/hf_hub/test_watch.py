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

from mirage.core.hf_hub.client import HfHubError
from mirage.core.hf_hub.tree import parse_entry
from mirage.core.hf_hub.watch import HfHubWalk, build_delta_hook
from tests.core.hf_hub.conftest import dir_row, file_row, ps


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.watch.fetch_tree")
async def test_walk_fingerprints_with_the_git_oid(mock_fetch, accessor):
    """git is content-addressed, so a rewrite that changed nothing keeps
    the oid and correctly reports nothing."""
    mock_fetch.return_value = {
        "a.txt": parse_entry(file_row("a.txt", 7)),
        "d": parse_entry(dir_row("d")),
    }
    rows = [e async for e in HfHubWalk(accessor)(ps(""))]
    by_path = {r.virtual: r for r in rows}
    assert by_path["/a.txt"].fingerprint == "oid-a.txt"
    assert by_path["/a.txt"].size == 7
    assert by_path["/d"].is_dir is True
    assert by_path["/d"].fingerprint is None


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.watch.fetch_tree")
async def test_walk_reseats_the_accessor_tree(mock_fetch, accessor):
    """Discarding it would leave find and du answering from the pre-pull
    listing, so a pull reporting a CREATE is followed by a find that
    cannot see the file."""
    mock_fetch.return_value = {"a.txt": parse_entry(file_row("a.txt"))}
    accessor.rows_cache = ("", {}, {})
    [e async for e in HfHubWalk(accessor)(ps(""))]
    assert accessor.tree_loaded is True
    assert accessor.rows_cache is None
    assert "a.txt" in accessor.tree


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.watch.fetch_tree")
async def test_walk_narrows_to_the_watch_root(mock_fetch, accessor):
    mock_fetch.return_value = {
        "a.txt": parse_entry(file_row("a.txt")),
        "d/b.txt": parse_entry(file_row("d/b.txt")),
    }
    rows = [e async for e in HfHubWalk(accessor)(ps("d"))]
    assert [r.virtual for r in rows] == ["/d/b.txt"]


def test_build_delta_hook_returns_a_hook(accessor):
    assert build_delta_hook(accessor) is not None


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.tree.hub_get_response")
async def test_walk_raises_for_a_repo_it_cannot_see(mock_get, accessor):
    # An expired token used to list as an empty repository, which a watch
    # pull reported as every file deleted.
    accessor.tree = {"a.txt": parse_entry(file_row("a.txt"))}
    accessor.tree_loaded = True
    tree = accessor.tree
    mock_get.side_effect = HfHubError("expired", 401)
    with pytest.raises(HfHubError):
        [e async for e in HfHubWalk(accessor)(ps(""))]
    assert accessor.tree is tree
