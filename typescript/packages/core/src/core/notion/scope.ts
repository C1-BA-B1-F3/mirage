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

import { ContentType } from '../../types.ts'
import { RAW } from '../hierarchy/codec.ts'
import { Scope, Slot, makeDetectScope } from '../hierarchy/scope.ts'

// A page tree nests arbitrarily, so the page level is one VARIADIC slot:
// `pages/a__1/b__2` is a page at any depth, and the slots hold the DEEPEST
// page's label and id, which is the one the path addresses. A database row
// is a page too, but one level of its own: the data source lists its rows as
// `rows.jsonl` rather than as directories, so a row is reached by its path
// alone and proves itself (`row` and `row_json`), while the pages under a
// row are listed by the row as any child page is.
const PAGE = new Slot('page', RAW, 'page_id', true)
const ROW = new Slot('row', RAW, 'row_id')
const DB: readonly (string | Slot)[] = ['databases', new Slot('database', RAW, 'database_id')]
const DS: readonly (string | Slot)[] = [...DB, new Slot('data_source', RAW, 'data_source_id')]

// One description of the tree: readdir, stat and read all classify through
// it, so the file surface cannot disagree with itself about what a path
// means. The `page` and `page_json` kinds are declared twice, once per
// root, because a page behaves identically wherever it hangs.
export const SCOPES: readonly Scope[] = [
  new Scope({ kind: 'pages', segments: ['pages'], probed: false }),
  new Scope({ kind: 'databases', segments: ['databases'], probed: false }),
  new Scope({
    kind: 'page_json',
    segments: ['pages', PAGE, 'page.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({ kind: 'page', segments: ['pages', PAGE] }),
  new Scope({
    kind: 'database_json',
    segments: [...DB, 'database.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({ kind: 'database', segments: DB }),
  new Scope({
    kind: 'data_source_json',
    segments: [...DS, 'data_source.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({
    kind: 'rows_jsonl',
    segments: [...DS, 'rows.jsonl'],
    leaf: true,
    filetype: ContentType.TEXT,
  }),
  new Scope({ kind: 'data_source', segments: DS }),
  new Scope({
    kind: 'row_json',
    segments: [...DS, ROW, 'page.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({ kind: 'row', segments: [...DS, ROW] }),
  new Scope({
    kind: 'page_json',
    segments: [...DS, ROW, PAGE, 'page.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({ kind: 'page', segments: [...DS, ROW, PAGE] }),
]

export const detectScope = makeDetectScope(SCOPES)
