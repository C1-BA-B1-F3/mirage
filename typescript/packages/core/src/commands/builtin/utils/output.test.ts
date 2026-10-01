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
import { formatOptionalRecords, formatRecords } from './output.ts'

const DEC = new TextDecoder()

describe('formatRecords', () => {
  it('empty returns empty bytes', () => {
    expect(formatRecords([]).length).toBe(0)
  })

  it('single record terminates line', () => {
    expect(DEC.decode(formatRecords(['a']))).toBe('a\n')
  })

  it('multiple records terminates last line', () => {
    expect(DEC.decode(formatRecords(['a', 'b']))).toBe('a\nb\n')
  })
})

describe('formatOptionalRecords', () => {
  it('empty returns null', () => {
    expect(formatOptionalRecords([])).toBeNull()
  })
})
