// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import type { SharePointAccessor } from '../../accessor/sharepoint.ts'
import { IndexEntry, ResourceType } from '../../cache/index/config.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import type { PathSpec } from '../../types.ts'
import { mountPrefixOf } from '../../utils/key_prefix.ts'
import { compareCodePoints } from '../../utils/sort.ts'
import { directoryPath, readdirItems, virtualKey } from '../msgraph/drive.ts'
import { driveLoc, listDrives, listSites, resolve } from './resolve.ts'

// A namespace level (the sites, or one site's libraries) is a listing of
// folders the index files like any other, so a stat below reads from it.
async function cacheNamespace(
  names: string[],
  key: string,
  base: string,
  prefix: string,
  index?: IndexCacheStore,
): Promise<string[]> {
  if (index !== undefined) {
    await index.setDir(
      key,
      names.map((name) => [
        name,
        new IndexEntry({ id: `${base}/${name}`, name, resourceType: ResourceType.FOLDER }),
      ]),
    )
  }
  return names.map((name) => `${prefix}${base}/${name}`).sort(compareCodePoints)
}

export async function readdir(
  accessor: SharePointAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<string[]> {
  const target = directoryPath(path)
  const key = virtualKey(path)
  if (index !== undefined) {
    const cached = await index.listDir(key)
    if (cached.entries !== undefined && cached.entries !== null) return cached.entries
  }
  const resolved = await resolve(accessor, target)
  const prefix = mountPrefixOf(target.virtual, target.vfsPath)
  if (resolved.level === 'root') {
    return cacheNamespace(await listSites(accessor), key, '', prefix, index)
  }
  if (resolved.level === 'site' && resolved.siteId !== null) {
    const drives = await listDrives(accessor, resolved.siteId)
    return cacheNamespace(drives, key, `/${target.vfsPath}`, prefix, index)
  }
  if (resolved.driveId === null) return []
  return readdirItems(
    accessor.config,
    driveLoc(accessor.config, resolved, target.vfsPath),
    index,
    prefix,
    target.vfsPath,
    key,
    target,
  )
}
