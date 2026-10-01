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

import type { OneDriveAccessor } from '../../accessor/onedrive.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import type { PathSpec } from '../../types.ts'
import { mountPrefixOf } from '../../utils/key_prefix.ts'
import { directoryPath, readdirItems, virtualKey } from '../msgraph/drive.ts'
import { driveLoc } from './client.ts'

export async function readdir(
  accessor: OneDriveAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<string[]> {
  const target = directoryPath(path)
  const key = virtualKey(path)
  if (index !== undefined) {
    const cached = await index.listDir(key)
    if (cached.entries !== undefined && cached.entries !== null) return cached.entries
  }
  return readdirItems(
    accessor.config,
    driveLoc(accessor.config, target.vfsPath),
    index,
    mountPrefixOf(target.virtual, target.vfsPath),
    target.vfsPath,
    key,
    target,
  )
}
