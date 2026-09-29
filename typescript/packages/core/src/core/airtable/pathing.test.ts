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
import { parseIdName } from '../../utils/naming.ts'
import { baseDirname, tableDirname, viewFilename } from './pathing.ts'

describe('airtable pathing', () => {
  it('joins sanitized labels to exact ids', () => {
    expect(baseDirname({ id: 'appOpsFinance0001', name: 'Ops / Finance ✓' })).toBe(
      'Ops_Finance__appOpsFinance0001',
    )
    expect(tableDirname({ id: 'tblBudget00000001', name: 'Q3 / Budget' })).toBe(
      'Q3_Budget__tblBudget00000001',
    )
    expect(viewFilename({ id: 'viwDone0000000001', name: 'Done / shipped' })).toBe(
      'Done_shipped__viwDone0000000001.jsonl',
    )
  })

  it('falls back to the id for a nameless entity', () => {
    expect(tableDirname({ id: 'tblX', name: '' })).toBe('tblX__tblX')
  })

  it('keeps the id when the label runs past NAME_MAX', () => {
    const name = viewFilename({ id: 'viwDone0000000001', name: '界'.repeat(200) })
    expect(new TextEncoder().encode(name).byteLength).toBeLessThanOrEqual(255)
    expect(parseIdName(name, '.jsonl')[1]).toBe('viwDone0000000001')
  })
})
