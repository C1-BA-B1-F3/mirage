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

import type { NotionAccessor } from '../../accessor/notion.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { assertParent } from '../hierarchy/probe.ts'
import type { IndexEntry } from '../../cache/index/config.ts'
import { ContentType, FileStat, FileType, type PathSpec } from '../../types.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import { makeStat } from '../hierarchy/stat.ts'
import { pageSegmentName } from './normalize.ts'
import { readdir } from './readdir.ts'
import { guardRow, resolveRow } from './resolve.ts'
import { detectScope } from './scope.ts'

function pageStat(_match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.DIRECTORY,
    modified: entry.remoteTime !== '' ? entry.remoteTime : null,
    extra: { page_id: entry.id },
  })
}

async function rowStat(
  accessor: NotionAccessor,
  match: ScopeMatch,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  await assertParent(stat, accessor, path, index)
  const page = await resolveRow(accessor, match, path.virtual)
  const name = pageSegmentName(page)
  const edited = typeof page.last_edited_time === 'string' ? page.last_edited_time : ''
  return new FileStat({
    name,
    type: FileType.DIRECTORY,
    modified: edited !== '' ? edited : null,
    extra: { page_id: typeof page.id === 'string' ? page.id : '' },
  })
}

async function rowJsonStat(
  accessor: NotionAccessor,
  match: ScopeMatch,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<FileStat> {
  await assertParent(stat, accessor, path, index)
  return new FileStat({ name: 'page.json', type: FileType.FILE, content: ContentType.JSON })
}

function pageJsonStat(_match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.FILE,
    content: ContentType.JSON,
    size: entry.size,
  })
}

function databaseStat(_match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.DIRECTORY,
    modified: entry.remoteTime !== '' ? entry.remoteTime : null,
    extra: { database_id: entry.id },
  })
}

function databaseJsonStat(match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.FILE,
    content: ContentType.JSON,
    size: entry.size,
    extra: { database_id: match.slots.database_id ?? '' },
  })
}

function dataSourceStat(_match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.DIRECTORY,
    modified: entry.remoteTime !== '' ? entry.remoteTime : null,
    extra: { data_source_id: entry.id },
  })
}

function dataSourceJsonStat(match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.FILE,
    content: ContentType.JSON,
    size: entry.size,
    extra: { data_source_id: match.slots.data_source_id ?? '' },
  })
}

function rowsJsonlStat(match: ScopeMatch, _path: PathSpec, entry: IndexEntry): FileStat {
  return new FileStat({
    name: entry.vfsName,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: entry.size,
    extra: { data_source_id: match.slots.data_source_id ?? '' },
  })
}

export const stat = makeStat(detectScope, readdir, {
  overrides: { row: rowStat, row_json: rowJsonStat },
  guards: { page: guardRow, page_json: guardRow },
  entryStats: {
    page: pageStat,
    page_json: pageJsonStat,
    database: databaseStat,
    database_json: databaseJsonStat,
    data_source: dataSourceStat,
    data_source_json: dataSourceJsonStat,
    rows_jsonl: rowsJsonlStat,
  },
})
