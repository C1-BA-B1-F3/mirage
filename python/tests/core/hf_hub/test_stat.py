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

import copy
from unittest.mock import AsyncMock, patch

import pytest

from mirage.cache.index import IndexEntry, LookupStatus
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.hf_hub.client import HfHubError
from mirage.core.hf_hub.stat import stat, stat_of
from mirage.core.hf_hub.tree import seed_index
from mirage.types import FileType
from tests.core.hf_hub.conftest import dir_row, file_row, page, ps, seed


@pytest.mark.asyncio
async def test_stat_of_the_mount_root_is_a_directory(loaded):
    result = await stat(loaded, ps(""))
    assert result.type is FileType.DIRECTORY
    assert result.name == "/"


@pytest.mark.asyncio
async def test_stat_reports_size_and_the_oid_as_fingerprint(loaded):
    result = await stat(loaded, ps("a.txt"))
    assert result.size == 7
    assert result.type is FileType.FILE
    assert result.fingerprint == "oid-a.txt"


@pytest.mark.asyncio
async def test_stat_of_a_directory_with_no_row_of_its_own(accessor):
    seed(accessor, file_row("d/b.txt"))
    result = await stat(accessor, ps("d"))
    assert result.type is FileType.DIRECTORY
    assert result.name == "d"


@pytest.mark.asyncio
async def test_stat_of_a_missing_path_is_enoent(loaded):
    with pytest.raises(FileNotFoundError):
        await stat(loaded, ps("nope"))


@pytest.mark.asyncio
async def test_stat_reports_the_lfs_object_size(accessor):
    """The 135-byte pointer is what git stores; the content size is what
    every reader needs, and reporting the pointer risks a short copy."""
    seed(
        accessor,
        file_row("w.bin",
                 4798702184,
                 lfs={
                     "oid": "sha",
                     "size": 4798702184,
                     "pointerSize": 135
                 }))
    result = await stat(accessor, ps("w.bin"))
    assert result.size == 4798702184
    assert result.extra["lfs_oid"] == "sha"


def test_stat_of_leaves_mtime_unset_when_the_row_has_none():
    """A Hub file's only mtime is its last commit, and a bare listing
    carries none. None is the honest answer; a repo-wide timestamp
    stamped on every file would be a confident lie."""
    assert stat_of(IndexEntry(id="o", name="f",
                              resource_type="file")).modified is None


def test_stat_of_reports_an_expanded_mtime():
    entry = IndexEntry(id="o",
                       name="f",
                       resource_type="file",
                       remote_time="2025-01-01T00:00:00.000Z")
    assert stat_of(entry).modified == "2025-01-01T00:00:00.000Z"


# An LFS row whose git oid, LFS sha and xet hash all differ: the stat's
# token has to be the oid, the same kind a tree row carries.
LFS_ROW = {
    "type": "file",
    "oid": "O",
    "size": 7,
    "path": "a.txt",
    "lfs": {
        "oid": "L"
    },
    "xetHash": "X",
}


def _point(rows):
    return patch("mirage.core.hf_hub.tree.hub_post",
                 AsyncMock(return_value=rows))


def _walk(*rows):
    return patch("mirage.core.hf_hub.tree.hub_get_response",
                 AsyncMock(return_value=page(list(rows))))


@pytest.mark.asyncio
async def test_a_probe_after_the_tree_loaded_asks_for_one_path(loaded):
    # A throwaway index (what reconcile passes) over a mount that has
    # already loaded its tree: one paths-info call, no tree walk.
    with _point([LFS_ROW]) as post, _walk() as walk:
        result = await stat(loaded, ps("a.txt"), RAMIndexCacheStore())
    assert post.await_count == 1
    walk.assert_not_awaited()
    assert post.await_args.args[2] == {"paths": ["a.txt"], "expand": False}
    assert (result.size, result.fingerprint) == (7, "O")


@pytest.mark.asyncio
async def test_a_point_stat_writes_nothing(loaded):
    tree = loaded.tree
    before = copy.deepcopy(tree)
    index = RAMIndexCacheStore()
    with _point([LFS_ROW]):
        await stat(loaded, ps("a.txt"), index)
    # No-index readers (local_rows) and the watch walk read accessor.tree
    # directly; a one-path answer that reseated or edited it would shrink the
    # listing they see to one file.
    assert loaded.tree is tree
    assert loaded.tree == before
    assert loaded.tree_loaded is True
    assert loaded.rows_cache is None
    assert (await index.list_dir("/")).status is LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_a_mount_that_never_loaded_walks_and_seeds(accessor):
    index = RAMIndexCacheStore()
    with _point([]) as post, _walk(file_row("a.txt", 7)) as walk:
        result = await stat(accessor, ps("a.txt"), index)
    post.assert_not_awaited()
    assert walk.await_count == 1
    assert result.fingerprint == "oid-a.txt"
    assert (await index.list_dir("/")).status is not LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_a_live_index_answers_without_a_request(loaded):
    index = RAMIndexCacheStore()
    seed_index(loaded, index, "")
    with _point([]) as post, _walk() as walk:
        result = await stat(loaded, ps("a.txt"), index)
    post.assert_not_awaited()
    walk.assert_not_awaited()
    assert result.fingerprint == "oid-a.txt"


@pytest.mark.asyncio
async def test_an_expired_index_refills_rather_than_asking_one_path(loaded):
    index = RAMIndexCacheStore()
    seed_index(loaded, index, "")
    await index.invalidate()
    with _point([]) as post, _walk(file_row("a.txt", 7)) as walk:
        await stat(loaded, ps("a.txt"), index)
    post.assert_not_awaited()
    assert walk.await_count == 1


@pytest.mark.asyncio
async def test_no_index_answers_from_the_loaded_tree(loaded):
    with _point([]) as post:
        result = await stat(loaded, ps("a.txt"))
    post.assert_not_awaited()
    assert result.fingerprint == "oid-a.txt"


@pytest.mark.asyncio
async def test_a_point_stat_of_a_missing_path_is_enoent_without_a_walk(loaded):
    tree = copy.deepcopy(loaded.tree)
    with _point([]) as post, _walk() as walk:
        with pytest.raises(FileNotFoundError):
            await stat(loaded, ps("nope"), RAMIndexCacheStore())
    assert post.await_count == 1
    walk.assert_not_awaited()
    assert loaded.tree == tree


@pytest.mark.asyncio
async def test_a_point_stat_of_a_directory(loaded):
    with _point([dir_row("d")]) as post, _walk() as walk:
        result = await stat(loaded, ps("d"), RAMIndexCacheStore())
    assert result.type is FileType.DIRECTORY
    assert post.await_count == 1
    walk.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, {}, {"error": "unavailable"}, ""])
async def test_a_malformed_point_stat_is_not_absence(loaded, answer):
    with _point(answer):
        with pytest.raises(HfHubError):
            await stat(loaded, ps("a.txt"), RAMIndexCacheStore())


@pytest.mark.asyncio
async def test_a_point_stat_refuses_rows_for_another_path(loaded):
    # An answer about some other path is not an answer about this one; it
    # must not read as absence, which reconcile would turn into a delete.
    with _point([file_row("A.TXT")]):
        with pytest.raises(HfHubError):
            await stat(loaded, ps("a.txt"), RAMIndexCacheStore())


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, ""), (403, ""),
                                         (404, "RepoNotFound"),
                                         (404, "RevisionNotFound")])
async def test_a_refused_point_stat_is_permission_denied(loaded, status, code):
    # Not absence (which reconcile turns into a delete) and not a raw Hub
    # error (which a recursive walk cannot step past).
    refused = AsyncMock(side_effect=HfHubError("nope", status, code))
    with patch("mirage.core.hf_hub.tree.hub_post", refused), _walk() as walk:
        with pytest.raises(PermissionError):
            await stat(loaded, ps("a.txt"), RAMIndexCacheStore())
    walk.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failing_point_stat_stays_a_hub_error(loaded):
    # A server failure is not a refusal; it keeps its own message.
    failed = AsyncMock(side_effect=HfHubError("boom", 500))
    with patch("mirage.core.hf_hub.tree.hub_post", failed), _walk():
        with pytest.raises(HfHubError, match="boom"):
            await stat(loaded, ps("a.txt"), RAMIndexCacheStore())


@pytest.mark.asyncio
async def test_a_refused_tree_walk_is_permission_denied(accessor):
    refused = AsyncMock(side_effect=HfHubError("nope", 401))
    with patch("mirage.core.hf_hub.tree.hub_get_response", refused):
        with pytest.raises(PermissionError):
            await stat(accessor, ps("a.txt"), RAMIndexCacheStore())


def test_stat_of_an_empty_id_carries_no_token():
    entry = IndexEntry(id="", name="a.txt", resource_type="file", size=1)
    assert stat_of(entry).fingerprint is None
