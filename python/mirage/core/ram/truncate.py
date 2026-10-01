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

from mirage.accessor.ram import RAMAccessor
from mirage.cache.context import invalidate_after_write
from mirage.core.ram.dest import check_dest_parents, check_write_target
from mirage.observe.context import record, start_op
from mirage.types import PathSpec
from mirage.utils.dates import now_iso
from mirage.utils.path import norm


async def truncate(
    accessor: RAMAccessor, path: PathSpec, length: int, no_create: bool = False
) -> None:
    store = accessor.store
    timer = start_op()
    p = norm(path.mount_path)
    check_dest_parents(store, path, p)
    check_write_target(store, path, p)
    if p in store.files:
        data = store.files[p]
    else:
        if no_create:
            return
        data = b""
    store.files[p] = data[:length].ljust(length, b"\0")
    store.modified[p] = now_iso()
    record("truncate", path.virtual, "ram", 0, timer)
    await invalidate_after_write(path)
