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

import type { GitHubAccessor } from '../../accessor/github.ts'
import type { IndexEntry } from '../../cache/index/config.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import type { PathSpec } from '../../types.ts'
import { FileStat, FileType } from '../../types.ts'
import { enoent } from '../../utils/errors.ts'
import { contentTypeForPath } from '../../utils/filetype.ts'
import { locate, lookupRetrying, pointLookup } from './lookup.ts'

// Render one tree row as a FileStat, the same from either route.
function statOf(entry: IndexEntry): FileStat {
  if (entry.resourceType === 'folder') {
    return new FileStat({ name: entry.name, type: FileType.DIRECTORY })
  }
  return new FileStat({
    name: entry.name,
    size: entry.size,
    type: FileType.FILE,
    content: contentTypeForPath(entry.name),
    fingerprint: entry.id,
    extra: { sha: entry.id },
  })
}

export async function stat(
  accessor: GitHubAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const { prefix, rel, key } = locate(path)
  if (rel === '') {
    return new FileStat({ name: '/', type: FileType.DIRECTORY })
  }
  if (index === undefined) throw enoent(path)
  // A probe through a throwaway index asks for this one path; everything
  // else answers from the mount's listing, filling it if need be.
  const found =
    (await pointLookup(accessor, index, prefix, rel)) ??
    (await lookupRetrying(accessor, index, prefix, key))
  if (found.entry === null) throw enoent(path)
  return statOf(found.entry)
}
