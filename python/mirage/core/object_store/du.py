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

from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.object_store.driver import (
    A,
    C,
    DuEntriesFn,
    DuSizeFn,
    ObjectStoreDriver,
)
from mirage.core.object_store.readdir import read_tree
from mirage.types import PathSpec
from mirage.utils import key_prefix as kp


def make_du_entries(driver: ObjectStoreDriver[A, C]) -> DuEntriesFn[A]:
    """Build the per-object size walk over one driver.

    Keys are stripped back to mount-relative paths, so a store mounted
    at a ``key_prefix`` reports the paths the user typed rather than the
    raw keys.

    Args:
        driver (ObjectStoreDriver): the store's native surface.
    """

    async def entries(
        accessor: A, path_spec: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> tuple[list[tuple[str, int]], int]:
        kpfx = driver.key_prefix_of(accessor)
        found: list[tuple[str, int]] = []
        total = 0
        rows, _ = await read_tree(driver, accessor, path_spec, index)
        for entry in rows:
            if not entry.key or entry.key.endswith("/"):
                continue
            rel = kp.strip(kpfx, entry.key)
            found.append(("/" + rel.lstrip("/"), entry.size or 0))
            total += entry.size or 0
        found.sort()
        return found, total

    return entries


def make_du_size(driver: ObjectStoreDriver[A, C]) -> DuSizeFn[A]:
    """Build the recursive byte total over one driver.

    Args:
        driver (ObjectStoreDriver): the store's native surface.
    """

    async def size(
        accessor: A, path_spec: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> int:
        rows, _ = await read_tree(driver, accessor, path_spec, index)
        return sum(
            entry.size or 0
            for entry in rows
            if entry.key and not entry.key.endswith("/")
        )

    return size
