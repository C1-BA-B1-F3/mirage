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

import type { GDocsAccessor } from '../../accessor/gdocs.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { MIME } from './constants.ts'
import { resolveAppEntry } from '../google/entry.ts'
import { makeFilename } from '../../vfs/gdocs/doc_entry.ts'
import { ContentType, FileStat, FileType, type PathSpec } from '../../types.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import { makeStat } from '../hierarchy/stat.ts'
import { readdir } from './readdir.ts'
import { detectScope } from './scope.ts'

async function fileStat(
  accessor: GDocsAccessor,
  match: ScopeMatch,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const entry = await resolveAppEntry(
    accessor.tokenManager,
    match,
    path,
    index,
    MIME,
    'gdocs/file',
    makeFilename,
  )
  return new FileStat({
    name: entry.vfsName !== '' ? entry.vfsName : entry.name,
    type: FileType.FILE,
    content: ContentType.JSON,
    modified: entry.remoteTime,
    size: entry.size,
    fingerprint: entry.remoteTime !== '' ? entry.remoteTime : null,
    extra: {
      doc_id: entry.id,
      doc_name: entry.name,
      ...entry.extra,
    },
  })
}

export const stat = makeStat(detectScope, readdir, { overrides: { file: fileStat } })
