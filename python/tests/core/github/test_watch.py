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

from mirage.accessor.github import GitHubAccessor
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.github.config import GitHubConfig
from mirage.core.github.tree import seed_index
from mirage.core.github.tree_entry import TreeEntry
from mirage.core.github.watch import GitHubWalk
from mirage.types import PathSpec
from mirage.watch.errors import IncompleteWalkError

CONFIG = GitHubConfig(token="t")


def _accessor(tree: dict[str, TreeEntry]) -> GitHubAccessor:
    return GitHubAccessor(
        config=CONFIG,
        owner="acme",
        repo="proj",
        ref="main",
        default_branch="main",
        tree=tree,
    )


def _root() -> PathSpec:
    return PathSpec(virtual="/gh", directory="/gh", vfs_path="")


def _entry(path: str, sha: str) -> TreeEntry:
    return TreeEntry(path=path, type="blob", sha=sha, size=3)


async def _collect(walk, root):
    return [entry async for entry in walk(root)]


@pytest.mark.asyncio
async def test_pull_refreshes_the_accessor_tree() -> None:
    # find, du and grep's scope counter read accessor.tree directly, so a
    # pull that fetched a newer tree and dropped it left them reporting the
    # repository as it stood when the mount was built.
    stale = {"a.txt": _entry("a.txt", "sha-a")}
    fresh = {
        "a.txt": _entry("a.txt", "sha-a"),
        "b.txt": _entry("b.txt", "sha-b"),
    }
    accessor = _accessor(stale)
    with patch(
        "mirage.core.github.watch.fetch_tree",
        return_value=(fresh, False, None),
    ):
        await _collect(GitHubWalk(accessor), _root())
    assert accessor.tree == fresh


@pytest.mark.asyncio
async def test_truncated_tree_is_not_adopted() -> None:
    # A partial tree would make find report the missing half as deleted.
    stale = {"a.txt": _entry("a.txt", "sha-a")}
    accessor = _accessor(stale)
    with patch(
        "mirage.core.github.watch.fetch_tree", return_value=({}, True, None)
    ):
        with pytest.raises(IncompleteWalkError):
            await _collect(GitHubWalk(accessor), _root())
    assert accessor.tree == stale


@pytest.mark.asyncio
async def test_walk_reports_blobs_with_their_sha() -> None:
    tree = {"a.txt": _entry("a.txt", "sha-a")}
    accessor = _accessor(tree)
    with patch(
        "mirage.core.github.watch.fetch_tree", return_value=(tree, False, None)
    ):
        entries = await _collect(GitHubWalk(accessor), _root())
    assert [(e.virtual, e.fingerprint) for e in entries] == [
        ("/gh/a.txt", "sha-a")
    ]


@pytest.mark.asyncio
async def test_complete_walk_clears_a_truncated_load() -> None:
    # A mount built from a truncated tree has no listing version. A walk
    # that fetched the whole tree replaced it but kept the truncated flag,
    # so the next seed still stamped no version and find kept walking the
    # per-directory fallback.
    stale = {"a.txt": _entry("a.txt", "sha-a")}
    fresh = {
        "a.txt": _entry("a.txt", "sha-a"),
        "b.txt": _entry("b.txt", "sha-b"),
    }
    accessor = GitHubAccessor(
        config=CONFIG,
        owner="acme",
        repo="proj",
        ref="main",
        default_branch="main",
        tree=stale,
        truncated=True,
    )
    with patch(
        "mirage.core.github.watch.fetch_tree",
        return_value=(fresh, False, "head-1"),
    ):
        await _collect(GitHubWalk(accessor), _root())
    assert accessor.truncated is False
    assert accessor.tree_version == "head-1"
    snapshot = seed_index(accessor, RAMIndexCacheStore(), "/gh/")
    assert snapshot.version == "head-1"


@pytest.mark.asyncio
async def test_truncated_walk_keeps_a_complete_load_and_its_version() -> None:
    # The walk refuses a truncated tree before reseating anything, so a
    # mount loaded complete keeps its tree, its flag and the head it was
    # loaded at: an older head the gate catches, never a partial tree
    # versioned as whole or a whole tree marked truncated.
    stale = {"a.txt": _entry("a.txt", "sha-a")}
    accessor = _accessor(stale)
    accessor.tree_loaded = True
    accessor.tree_version = "head-0"
    with patch(
        "mirage.core.github.watch.fetch_tree",
        return_value=({}, True, "head-1"),
    ):
        with pytest.raises(IncompleteWalkError):
            await _collect(GitHubWalk(accessor), _root())
    assert accessor.truncated is False
    assert accessor.tree_version == "head-0"
    assert accessor.tree == stale
    snapshot = seed_index(accessor, RAMIndexCacheStore(), "/gh/")
    assert snapshot.version == "head-0"
