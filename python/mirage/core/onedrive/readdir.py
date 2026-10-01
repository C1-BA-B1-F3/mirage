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

from mirage.accessor.onedrive import OneDriveAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.msgraph.drive import (directory_path, readdir_items,
                                       virtual_key)
from mirage.core.onedrive.client import drive_loc
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of


async def readdir(accessor: OneDriveAccessor,
                  path: PathSpec,
                  index: IndexCacheStore = NULL_INDEX) -> list[str]:
    target = directory_path(path)
    key = virtual_key(path)
    listing = await index.list_dir(key)
    if listing.entries is not None:
        return listing.entries
    return await readdir_items(accessor.config,
                               drive_loc(accessor.config, target.vfs_path),
                               index,
                               mount_prefix_of(target.virtual,
                                               target.vfs_path),
                               target.vfs_path,
                               key,
                               session=accessor.pool)
