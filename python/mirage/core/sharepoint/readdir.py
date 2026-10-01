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

from mirage.accessor.sharepoint import SharePointAccessor
from mirage.cache.index import (NULL_INDEX, IndexCacheStore, IndexEntry,
                                ResourceType)
from mirage.core.msgraph.drive import (directory_path, readdir_items,
                                       virtual_key)
from mirage.core.sharepoint.resolve import (drive_loc, list_drives, list_sites,
                                            resolve)
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of


async def _cache_namespace(names: list[str], key: str, base: str, prefix: str,
                           index: IndexCacheStore) -> list[str]:
    """File a namespace level (the sites, or one site's libraries).

    It is a listing of folders the index files like any other, so a stat
    below reads from it.

    Args:
        names (list[str]): the level's entries.
        key (str): the listing's index key.
        base (str): the level's mount-relative path, "" for the root.
        prefix (str): the mount prefix the output carries.
        index (IndexCacheStore): the index to file the listing in.
    """
    await index.set_dir(key, [(name,
                               IndexEntry(id=f"{base}/{name}",
                                          name=name,
                                          resource_type=ResourceType.FOLDER))
                              for name in names])
    return sorted(f"{prefix}{base}/{name}" for name in names)


async def readdir(accessor: SharePointAccessor,
                  path: PathSpec,
                  index: IndexCacheStore = NULL_INDEX) -> list[str]:
    target = directory_path(path)
    key = virtual_key(path)
    listing = await index.list_dir(key)
    if listing.entries is not None:
        return listing.entries
    resolved = await resolve(accessor, target)
    prefix = mount_prefix_of(target.virtual, target.vfs_path)
    if resolved.level == "root":
        return await _cache_namespace(await list_sites(accessor), key, "",
                                      prefix, index)
    if resolved.level == "site" and resolved.site_id is not None:
        drives = await list_drives(accessor, resolved.site_id)
        return await _cache_namespace(drives, key, "/" + target.vfs_path,
                                      prefix, index)
    if resolved.drive_id is None:
        return []
    return await readdir_items(accessor.config,
                               drive_loc(accessor.config, resolved,
                                         target.vfs_path),
                               index,
                               prefix,
                               target.vfs_path,
                               key,
                               session=accessor.pool)
