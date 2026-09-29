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

import type { LangfuseAccessor } from '../../accessor/langfuse.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { ContentType, FileStat, FileType, type PathSpec } from '../../types.ts'
import { stripSlash } from '../../utils/slash.ts'
import { listedSize, resolveEntry } from '../hierarchy/probe.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import { makeStat } from '../hierarchy/stat.ts'
import { jsonBytes } from '../render/json.ts'
import { fetchTraceFile } from './read.ts'
import { readdir } from './readdir.ts'
import { detectScope } from './scope.ts'

function sessionExtra(match: ScopeMatch): Record<string, string> {
  return { session_id: match.slots.session_id ?? '' }
}

function promptExtra(match: ScopeMatch): Record<string, string> {
  return { prompt_name: match.slots.prompt_name ?? '' }
}

function datasetExtra(match: ScopeMatch): Record<string, string> {
  return { dataset_name: match.slots.dataset_name ?? '' }
}

// A trace listing stops at defaultTraceLimit and defaultFromTimestamp while
// read fetches any trace by id, so a trace the listing left out is probed
// the way read reaches it; the probe fetched the whole trace, so its
// rendered size is exact. Mirrors python's `_stat_trace`.
async function statTrace(
  accessor: LangfuseAccessor,
  match: ScopeMatch,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  const name = stripSlash(path.vfsPath).split('/').pop() ?? ''
  const entry = await resolveEntry(readdir, accessor, path, index)
  const size =
    entry !== null
      ? await listedSize(index, path)
      : jsonBytes(await fetchTraceFile(accessor, match, path)).byteLength
  return new FileStat({ name, type: FileType.FILE, content: ContentType.JSON, size })
}

export const stat = makeStat(detectScope, readdir, {
  overrides: {
    trace: statTrace,
    session_trace: statTrace,
  },
  extras: {
    session: sessionExtra,
    prompt: promptExtra,
    dataset: datasetExtra,
  },
})
