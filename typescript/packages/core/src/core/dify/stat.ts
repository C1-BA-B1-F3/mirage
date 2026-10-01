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
import { DIFY_TREE, extractDocumentSize } from './tree.ts'

// Index-only stat: never fetches document detail, so `ls` and the plain
// `find` walk stay cheap (one listing per mount, no per-entry API call).
// size stays null because the entry size is the uploaded source file
// (e.g. the original PDF), not the rendered segment text this mount
// serves (FileStat.size must be render-derived or null, see the
// CLAUDE.md FUSE rules). The source size remains in extra.source_size.
export async function statLight(
  accessor: DifyAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const resolved = await DIFY_TREE.resolve(accessor, path, index)
  if (resolved.isDir) return directoryStat(resolved)
  const extra: Record<string, unknown> = { ...resolved.entry.extra }
  if (resolved.entry.size !== null) {
    extra.source_size = resolved.entry.size
  }
  const modified = resolved.entry.remoteTime
  return new FileStat({
    name: resolved.entry.name,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: null,
    modified: modified !== '' ? modified : null,
    fingerprint: null,
    revision: null,
    extra,
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
  const sourceSize = extractDocumentSize(detail) ?? resolved.entry.size
  const extra: Record<string, unknown> = { ...resolved.entry.extra }
  extra.document_id = resolved.entry.id
  // size stays null: the API reports the uploaded source file's size (e.g.
  // the original PDF), not the rendered segment text this mount serves
  // (FileStat.size must be render-derived or null, see the CLAUDE.md FUSE
  // rules). The source size remains in extra.
  if (sourceSize !== null) {
    extra.source_size = sourceSize
  }
  if ('tokens' in detail) {
    extra.tokens = detail.tokens
  }
  if ('indexing_status' in detail) {
    extra.indexing_status = detail.indexing_status
  }
  return new FileStat({
    name: resolved.entry.name,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: null,
    modified: timestampToZulu(detail.updated_at),
    fingerprint: null,
    revision: null,
    extra,
  })
}

// Mirrors the Python timestamp_to_zulu over its real domain (the API
// sends epoch seconds or nothing): second precision and a literal Z,
// unlike tree.ts's timestampToIso (+millis); strings pass through.
function timestampToZulu(value: unknown): string | null {
  if (typeof value === 'number') {
    return new Date(value * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')
  }
  return typeof value === 'string' ? value : null
}
