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
import { CharSet } from './charset.ts'
import {
  canonicalCategory,
  category,
  fold,
  foldOrbits,
  pcreWord,
  rustWord,
  unicodeProperty,
} from './unicode_tables.ts'

describe('unicode tables', () => {
  it.each([
    ['L', 'L'],
    ['Lu', 'Lu'],
    ['letter', 'L'],
    ['Decimal_Number', 'Nd'],
    ['decimal number', 'Nd'],
    ['gc=Nd', 'Nd'],
    ['General_Category=Lu', 'Lu'],
    ['Greek', null],
  ] as [string, string | null][])('reads %j as %j', (name, short) => {
    expect(canonicalCategory(name)).toBe(short)
  })

  it('holds what each category name says', () => {
    expect(category('Nd').contains(0x663)).toBe(true)
    expect(category('Lu').contains(0xc9)).toBe(true)
    expect(category('Lu').contains(0xe9)).toBe(false)
    expect(category('L').contains(0xe9)).toBe(true)
  })

  it('spells the properties both dialects share', () => {
    expect(unicodeProperty('Any')?.contains(0x10ffff)).toBe(true)
    expect(unicodeProperty('ASCII')?.equals(CharSet.of([0, 0x7f]))).toBe(true)
    expect(unicodeProperty('Assigned')?.contains(0x0378)).toBe(false)
    expect(unicodeProperty('Greek')).toBeNull()
  })

  // Measured with ripgrep 14.1.1 and PCRE2 10.43; the rows are
  // `test_unicode_tables.py`'s own.
  it.each([
    [233, true, true],
    [1633, true, true],
    [769, true, true],
    [8255, true, true],
    [178, false, true],
    [8544, true, true],
    [9398, true, false],
    [8204, true, false],
    [32, false, false],
  ] as [number, boolean, boolean][])('U+%s: rust %j, pcre %j', (cp, rust, pcre) => {
    expect(rustWord().contains(cp)).toBe(rust)
    expect(pcreWord().contains(cp)).toBe(pcre)
  })

  it('folds with simple case folding', () => {
    const orbits = foldOrbits()
    expect(orbits.get(0x6b)).toEqual([0x4b, 0x6b, 0x212a])
    expect(orbits.get(0x73)).toEqual([0x53, 0x73, 0x17f])
    expect(orbits.has(0x131)).toBe(false)
    expect(orbits.get(0xdf)).toEqual([0xdf, 0x1e9e])
    expect(fold(CharSet.chars(0x6b), true).equals(CharSet.chars(0x4b, 0x6b))).toBe(true)
    expect(fold(CharSet.of([0x61, 0x63]), false).contains(0x42)).toBe(true)
  })
})
