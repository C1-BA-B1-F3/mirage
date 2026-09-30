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
import { ALL, CharSet, MAX_CODE_POINT, hostChar, hostClass } from './charset.ts'

describe('CharSet', () => {
  it('merges overlapping and adjacent ranges', () => {
    expect(CharSet.of([5, 9], [1, 3], [4, 4], [20, 22]).ranges).toEqual([
      [1, 9],
      [20, 22],
    ])
  })

  it('does the set algebra a class needs', () => {
    const a = CharSet.of([0x61, 0x7a])
    const b = CharSet.of([0x6d, 0x70])
    expect(a.intersect(b).equals(b)).toBe(true)
    expect(a.minus(b).ranges).toEqual([
      [0x61, 0x6c],
      [0x71, 0x7a],
    ])
    expect(a.xor(CharSet.of([0x78, 0x7e])).ranges).toEqual([
      [0x61, 0x77],
      [0x7b, 0x7e],
    ])
    expect(b.union(a).equals(a)).toBe(true)
  })

  it('negates over the scalar values', () => {
    const negated = CharSet.chars(0x61).negate()
    expect(negated.contains(0x61)).toBe(false)
    expect(negated.contains(0xd800)).toBe(false)
    expect(negated.contains(MAX_CODE_POINT)).toBe(true)
    expect(negated.negate().equals(CharSet.chars(0x61))).toBe(true)
    expect(ALL.contains(0xdfff)).toBe(false)
  })

  it('answers single and empty', () => {
    expect(CharSet.chars(7).single()).toBe(7)
    expect(CharSet.of([1, 2]).single()).toBeNull()
    expect(new CharSet().isEmpty()).toBe(true)
  })
})

describe('host emission', () => {
  it('keeps printable ASCII readable', () => {
    expect(hostChar(0x61)).toBe('a')
    expect(hostChar(0x2e)).toBe('\\.')
    expect(hostChar(0x2d)).toBe('-')
    expect(new RegExp('^' + hostChar(0xa0) + '$', 'u').test(String.fromCodePoint(0xa0))).toBe(true)
    expect(new RegExp('^' + hostChar(0x1f600) + '$', 'u').test(String.fromCodePoint(0x1f600))).toBe(
      true,
    )
  })

  it('spells a class that matches exactly its members', () => {
    for (const cs of [
      CharSet.chars(0x5d, 0x5e, 0x2d),
      CharSet.of([0x20, 0x7e]).negate(),
      new CharSet(),
    ]) {
      const pattern = new RegExp('^' + hostClass(cs) + '$', 'u')
      for (const cp of [0x20, 0x5d, 0x5e, 0x2d, 0xa0, 0x1f600, 0xdc80]) {
        expect(pattern.test(String.fromCodePoint(cp))).toBe(cs.contains(cp))
      }
    }
  })
})
