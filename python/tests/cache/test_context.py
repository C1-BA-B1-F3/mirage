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

import asyncio

import pytest

from mirage.cache.context import (active_cache_manager,
                                  invalidate_after_unlink,
                                  invalidate_after_write, invalidate_ancestors,
                                  invalidate_subtree, push_cache_manager)
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.manager import CacheManager
from mirage.types import PathSpec


def _run(coro):
    return asyncio.run(coro)


class FakeManager:

    def listed_since(self, _folder: str, _started: int) -> bool:
        return False

    def __init__(self) -> None:
        self.writes: list[PathSpec] = []
        self.unlinks: list[PathSpec] = []
        self.subtrees: list[PathSpec] = []
        self.ancestors: list[PathSpec] = []

    async def invalidate_after_write(self, path: PathSpec) -> None:
        self.writes.append(path)

    async def invalidate_after_unlink(self, path: PathSpec) -> None:
        self.unlinks.append(path)

    async def invalidate_ancestors(self, path: PathSpec) -> None:
        self.ancestors.append(path)

    async def invalidate_subtree(self, path: PathSpec) -> None:
        self.subtrees.append(path)


def _spec(virtual: str) -> PathSpec:
    return PathSpec(vfs_path=virtual.strip("/"),
                    virtual=virtual,
                    directory="/",
                    pattern=None,
                    resolved=True)


async def _delegates() -> FakeManager:
    manager = FakeManager()
    prev = push_cache_manager(manager)
    await invalidate_after_write(_spec("/a.txt"))
    await invalidate_after_unlink(_spec("/b.txt"))
    await invalidate_subtree(_spec("/c"))
    push_cache_manager(prev)
    return manager


def test_delegates_to_active_manager():
    manager = _run(_delegates())
    assert [p.mount_path for p in manager.writes] == ["/a.txt"]
    assert [p.mount_path for p in manager.unlinks] == ["/b.txt"]
    assert [p.mount_path for p in manager.subtrees] == ["/c"]


async def _noop_without_manager() -> None:
    push_cache_manager(None)
    await invalidate_after_write(_spec("/a.txt"))
    await invalidate_after_unlink(_spec("/b.txt"))
    await invalidate_subtree(_spec("/c"))
    await invalidate_ancestors(_spec("/c/d"))


def test_noop_without_active_manager():
    _run(_noop_without_manager())


async def _push_restores() -> tuple[object, object, object]:
    first = FakeManager()
    second = FakeManager()
    prev0 = push_cache_manager(first)
    prev1 = push_cache_manager(second)
    active = active_cache_manager()
    push_cache_manager(prev1)
    restored = active_cache_manager()
    push_cache_manager(prev0)
    return prev1, active, restored


def test_push_returns_previous_manager():
    prev1, active, restored = _run(_push_restores())
    assert prev1 is not None
    assert active is not restored
    assert restored is prev1


async def _ancestors() -> FakeManager:
    manager = FakeManager()
    prev = push_cache_manager(manager)
    await invalidate_ancestors(
        PathSpec(vfs_path="data/a/b.txt",
                 virtual="/data/data/a/b.txt",
                 directory="/data/data/a"))
    push_cache_manager(prev)
    return manager


def test_invalidate_ancestors_preserves_virtual_path():
    manager = _run(_ancestors())
    assert [p.virtual for p in manager.ancestors] == ["/data/data/a/b.txt"]
    assert manager.writes == []


async def _repeated_mount_case(prefix: str) -> None:
    index = RAMIndexCacheStore(ttl=600)
    manager = CacheManager(None, index, prefix, True)
    directory = prefix + prefix + "/a"
    ancestors = [prefix, prefix + prefix, directory]
    for ancestor in ancestors:
        await index.set_dir(ancestor, [])
    await index.set_dir(prefix + "/unrelated", [])
    path = PathSpec(vfs_path=directory[len(prefix):].strip("/") + "/b.txt",
                    virtual=directory + "/b.txt",
                    directory=directory)
    previous = push_cache_manager(manager)
    try:
        await invalidate_after_write(path)
        await invalidate_ancestors(path)
    finally:
        push_cache_manager(previous)
    for ancestor in ancestors:
        assert (await index.list_dir(ancestor)).entries is None
    assert (await index.list_dir(prefix + "/unrelated")).entries is not None


@pytest.mark.parametrize("prefix", ["/data", "/nested/data"])
def test_ancestor_eviction_with_repeated_mount_name(prefix: str):
    _run(_repeated_mount_case(prefix))
