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

import type { DropboxAccessor } from '../../../accessor/dropbox.ts'
import type { IndexCacheStore } from '../../../cache/index/store.ts'
import { narrowPaths } from '../../../core/dropbox/search.ts'
import { stat as dropboxStat } from '../../../core/dropbox/stat.ts'
import { FileType, type PathSpec } from '../../../types.ts'
import { resolveGlobOf } from '../generic_bind/index.ts'
import { textCandidates, wholeWordLiteral } from '../grep_pushdown.ts'
import { DROPBOX_IO } from './io.ts'

const resolveGlob = resolveGlobOf(DROPBOX_IO)

export interface NarrowResult {
  resolved: PathSpec[]
  usedSearch: boolean
}

async function allDirectories(
  accessor: DropboxAccessor,
  paths: readonly PathSpec[],
  index?: IndexCacheStore,
): Promise<boolean> {
  for (const p of paths) {
    try {
      const s = await dropboxStat(accessor, p, index)
      if (s.type !== FileType.DIRECTORY) return false
    } catch {
      // File operands keep the exact single-file output shape and missing
      // operands must surface the walk's error message; both fall back.
      return false
    }
  }
  return true
}

// Resolve grep/rg scope paths, narrowing via Dropbox file search. Push-down
// needs every gate to hold: the mount opted in via contentSearch, the scan
// is recursive, a whole-word literal can be pushed down (wholeWordLiteral,
// which is what makes a word-based search complete), the output mode
// tolerates a narrowed-superset file set (exactFileSet covers flags like -v
// that must see every file), and every scope operand is a directory. Unlike
// the GitHub narrow there is no scope-size gate: one search call plus
// targeted downloads beats a readdir-walk-plus-download-everything scan at
// every scope size. An empty search result still falls back to the full
// scan (GitHub parity) because search indexing lags recent writes.
// Binary-extension candidates are dropped from the narrowed set because the
// recursive walk it replaces skips them; a narrowed set may therefore be
// empty, which callers must not treat as a stdin run.
export async function narrowScope(
  accessor: DropboxAccessor,
  paths: PathSpec[],
  pattern: string | null,
  opts: {
    fixedString: boolean
    recursive: boolean
    wholeWord: boolean
    exactFileSet: boolean
    index?: IndexCacheStore
  },
): Promise<NarrowResult> {
  const query = wholeWordLiteral(pattern, opts.fixedString, opts.wholeWord)
  const useSearch =
    query !== null &&
    opts.recursive &&
    !opts.exactFileSet &&
    accessor.contentSearch &&
    (await allDirectories(accessor, paths, opts.index))
  if (useSearch) {
    const narrowed = await narrowPaths(accessor, query, paths)
    if (narrowed !== null && narrowed.length > 0) {
      return { resolved: textCandidates(narrowed), usedSearch: true }
    }
  }
  const resolved = await resolveGlob(accessor, paths, opts.index)
  return { resolved, usedSearch: false }
}
