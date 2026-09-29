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
import { AirtableApiError, errorParts } from './errors.ts'

describe('airtable errors', () => {
  it('reads every error body shape', () => {
    expect(errorParts('{"error": {"type": "X", "message": "m"}}')).toEqual(['X', 'm'])
    expect(errorParts('{"error": {"type": "LIST_RECORDS_ITERATOR_NOT_AVAILABLE"}}')).toEqual([
      'LIST_RECORDS_ITERATOR_NOT_AVAILABLE',
      null,
    ])
    expect(errorParts('{"error": "NOT_FOUND"}')).toEqual(['NOT_FOUND', null])
    expect(errorParts('not json')).toEqual([null, null])
    expect(errorParts('[1]')).toEqual([null, null])
  })

  it("counts airtable's 403 answer as not found", () => {
    expect(new AirtableApiError('m', 404).notFound).toBe(true)
    expect(new AirtableApiError('m', 403, 'INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND').notFound).toBe(
      true,
    )
    expect(new AirtableApiError('m', 422, 'INVALID_REQUEST').notFound).toBe(false)
  })

  it('counts a missing view as not found by id or by name', () => {
    for (const type of ['VIEW_ID_NOT_FOUND', 'VIEW_NAME_NOT_FOUND']) {
      expect(new AirtableApiError('m', 422, type).notFound).toBe(true)
    }
  })
})
