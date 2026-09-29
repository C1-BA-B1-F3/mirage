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

import { describe, expect, it } from 'vitest'
import { detectScope } from './scope.ts'

const BASE = 'bases/Roadmap__appRoadmapBase001'
const TABLE = `${BASE}/Features__tblFeatures000001`

describe('airtable scope', () => {
  it.each([
    ['/', 'root', {}],
    ['/bases', 'bases', {}],
    [`/${BASE}`, 'base', { base_id: 'appRoadmapBase001' }],
    [`/${BASE}/base.json`, 'base_json', { base_id: 'appRoadmapBase001' }],
    [`/${TABLE}`, 'table', { table_id: 'tblFeatures000001' }],
    [`/${TABLE}/table.json`, 'table_json', { table_id: 'tblFeatures000001' }],
    [`/${TABLE}/records.jsonl`, 'records', { table_id: 'tblFeatures000001' }],
    [`/${TABLE}/views`, 'views', {}],
    [`/${TABLE}/views/Done__viwDone0000000001.jsonl`, 'view', { view_id: 'viwDone0000000001' }],
    [`/${TABLE}/views/Done__viwDone0000000001.json`, 'invalid', {}],
    [`/${BASE}/no_separator`, 'invalid', {}],
    [`/${TABLE}/.hidden`, 'invalid', {}],
  ])('classifies %s as %s', (path, kind, slots) => {
    const match = detectScope(path)
    expect(match.kind).toBe(kind)
    for (const [key, value] of Object.entries(slots)) expect(match.slots[key]).toBe(value)
  })
})
