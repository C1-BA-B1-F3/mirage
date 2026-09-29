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

import aiofiles.os

from mirage.accessor.disk import DiskAccessor
from mirage.cache.context import invalidate_subtree
from mirage.core.disk.utils import resolve_inside
from mirage.types import PathSpec


async def rename(accessor: DiskAccessor, src_spec: PathSpec,
                 dst_spec: PathSpec) -> None:
    root = accessor.root
    await invalidate_subtree(src_spec)
    # Both sides are subtree evictions: a rename destroys the destination's
    # previous identity and relocates everything under the source, so a
    # listing or body cached below either name is now stale.
    await invalidate_subtree(dst_spec)
    await aiofiles.os.rename(await resolve_inside(root, src_spec), await
                             resolve_inside(root, dst_spec))
