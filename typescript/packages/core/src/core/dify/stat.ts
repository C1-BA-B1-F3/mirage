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

import type { DifyAccessor } from '../../accessor/dify.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { ContentType, FileStat, FileType, type PathSpec } from '../../types.ts'
import { directoryStat } from '../slug_tree/stat.ts'
import { getDocumentDetail } from './client.ts'
import { DIFY_TREE, epochText, extractDocumentSize } from './tree.ts'

// Index-only stat: never fetches document detail, so `ls` and the plain
// `find` walk stay cheap (one listing per mount, no per-entry API call).
export async function statLight(
  accessor: DifyAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const resolved = await DIFY_TREE.resolve(accessor, path, index)
  if (resolved.isDir) return directoryStat(resolved)
  const created = resolved.entry.remoteTime !== '' ? resolved.entry.remoteTime : null
  return new FileStat({
    name: resolved.entry.name,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: null,
    modified: created,
    birthtime: created,
    fingerprint: null,
    revision: null,
    extra: { ...resolved.entry.extra },
  })
}

export async function stat(
  accessor: DifyAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const resolved = await DIFY_TREE.resolve(accessor, path, index)
  if (resolved.isDir) return directoryStat(resolved)
  const detail = await getDocumentDetail(accessor, resolved.entry.id)
  const extra: Record<string, unknown> = { ...resolved.entry.extra }
  extra.document_id = resolved.entry.id
  const sourceSize = extractDocumentSize(detail)
  if (sourceSize !== null) {
    extra.source_size = sourceSize
  }
  if ('tokens' in detail) {
    extra.tokens = detail.tokens
  }
  if ('indexing_status' in detail) {
    extra.indexing_status = detail.indexing_status
  }
  const created =
    epochText(detail.created_at) ??
    (resolved.entry.remoteTime !== '' ? resolved.entry.remoteTime : null)
  return new FileStat({
    name: resolved.entry.name,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: null,
    modified: epochText(detail.updated_at) ?? created,
    birthtime: created,
    fingerprint: null,
    revision: null,
    extra,
  })
}
