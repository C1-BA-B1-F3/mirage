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
import { invalidateAfterWrite, invalidateAncestors } from '../../cache/context.ts'
import type { PathSpec } from '../../types.ts'
import { GraphError } from '../msgraph/client.ts'
import { baseName, createChildFolder, parentPath } from '../msgraph/drive.ts'
import { fullItemUrl, itemUrl } from './client.ts'

/**
 * Create the mount's `keyPrefix` folders, one level at a time.
 *
 * The mount root exists from the agent's side because it is mounted, but on
 * the drive it is a folder chain nothing has created until the first write.
 * A file upload creates its parents; a folder create does not, so mkdir has
 * to.
 *
 * Args:
 *   accessor: the mount's accessor.
 */
async function createRoot(accessor: OneDriveAccessor): Promise<void> {
  let parent = ''
  for (const name of accessor.config.keyPrefix.split('/')) {
    await createChildFolder(
      accessor.config,
      fullItemUrl(accessor.config, parent, '/children'),
      name,
    )
    parent = parent === '' ? name : `${parent}/${name}`
  }
}

async function createDir(accessor: OneDriveAccessor, path: string): Promise<void> {
  const parent = parentPath(path)
  const url = itemUrl(accessor.config, parent, '/children')
  try {
    await createChildFolder(accessor.config, url, baseName(path))
  } catch (error) {
    const missingRoot =
      error instanceof GraphError &&
      error.status === 404 &&
      parent === '' &&
      accessor.config.keyPrefix !== ''
    if (!missingRoot) throw error
    await createRoot(accessor)
    await createChildFolder(accessor.config, url, baseName(path))
  }
}

export async function mkdir(
  accessor: OneDriveAccessor,
  path: PathSpec,
  parents = false,
): Promise<void> {
  const key = path.vfsPath
  if (key === '') return
  if (parents) {
    const parts = key.split('/')
    for (let index = 1; index <= parts.length; index++) {
      await createDir(accessor, parts.slice(0, index).join('/'))
    }
  } else {
    await createDir(accessor, key)
  }
  await invalidateAfterWrite(path)
  if (parents) await invalidateAncestors(path)
}
