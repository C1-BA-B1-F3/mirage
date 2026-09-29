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
import { JSONL_NAME, RAW } from '../hierarchy/codec.ts'
import { Scope, Slot, makeDetectScope } from '../hierarchy/scope.ts'

const BASE: readonly (string | Slot)[] = ['bases', new Slot('base', RAW, 'base_id')]
const TABLE: readonly (string | Slot)[] = [...BASE, new Slot('table', RAW, 'table_id')]

// One description of the tree for readdir, stat and read. A base holds only
// tables, so a table directory sits right under its base beside base.json;
// the literal leaves are declared before the table slot, and a table's
// `label__tbl...` name can never spell one of them anyway.
export const SCOPES: readonly Scope[] = [
  new Scope({ kind: 'bases', segments: ['bases'], probed: false }),
  new Scope({ kind: 'base', segments: BASE }),
  new Scope({
    kind: 'base_json',
    segments: [...BASE, 'base.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({ kind: 'table', segments: TABLE }),
  new Scope({
    kind: 'table_json',
    segments: [...TABLE, 'table.json'],
    leaf: true,
    filetype: ContentType.JSON,
  }),
  new Scope({
    kind: 'records',
    segments: [...TABLE, 'records.jsonl'],
    leaf: true,
    filetype: ContentType.TEXT,
  }),
  new Scope({ kind: 'views', segments: [...TABLE, 'views'] }),
  new Scope({
    kind: 'view',
    segments: [...TABLE, 'views', new Slot('view', JSONL_NAME, 'view_id')],
    leaf: true,
    filetype: ContentType.TEXT,
  }),
]

export const detectScope = makeDetectScope(SCOPES)
