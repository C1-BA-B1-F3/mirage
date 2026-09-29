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
import { InputPositions, linesRead, valueEnd } from './position.ts'

/** Every "1 " value on the first line, placed at the space after it. */
function counts(text: string, numbers: number): number[] {
  const first = text.indexOf('1 ')
  return linesRead(
    text,
    Array.from({ length: numbers }, (_, k) => first + 2 * k + 1),
  )
}

function tally(values: number[]): [number, number] {
  return [values.filter((v) => v === 0).length, values.filter((v) => v === 1).length]
}

describe('valueEnd', () => {
  it.each([
    ['"a" 1', 3, 2],
    ['[1] ', 3, 2],
    ['{} ', 2, 1],
    ['12 3', 2, 2],
    ['true', 4, 4],
  ])('places %j whole at %i as %i', (text, stop, expected) => {
    expect(valueEnd(text, stop)).toBe(expected)
  })
})

describe('linesRead', () => {
  it('counts the newlines read through each line', () => {
    const text = '1 2\n3\n4'
    expect(linesRead(text, [1, 3, 5, text.length])).toEqual([1, 1, 2, 2])
  })

  it('counts a long line once the reader holds its last piece', () => {
    // jq 1.8.2 reads a long line 4091 bytes at a time: of 4095 values on
    // one 8190-byte line, only the last four arrive with its newline.
    expect(tally(counts('1 '.repeat(4095) + '\n2\n', 4095))).toEqual([4091, 4])
  })

  it('reads a piece on to the end of a character', () => {
    // The first piece ends inside an é, reads one more byte to finish it,
    // and so every later piece starts a byte on (pinned: 2044 and 56).
    const text = '"a' + 'é'.repeat(2045) + '"  ' + '1 '.repeat(2100) + '\n'
    expect(tally(counts(text, 2100))).toEqual([2044, 56])
  })
})

describe('InputPositions', () => {
  it('names each input and its lines', () => {
    const positions = new InputPositions(
      ['<stdin>', 'b.json'],
      ['1\n2\n', '3'],
      [
        [0, 1],
        [0, 3],
        [1, 1],
      ],
    )
    expect([0, 1, 2].map((doc) => positions.at(doc))).toEqual([
      '<stdin>:1',
      '<stdin>:2',
      'b.json:0',
    ])
    expect(positions.end()).toBe('b.json:0')
  })

  it('stands a document with no input at the end', () => {
    const positions = new InputPositions([], [], [])
    expect(positions.at(0)).toBe('<stdin>:0')
    expect(positions.end()).toBe('<stdin>:0')
  })
})
