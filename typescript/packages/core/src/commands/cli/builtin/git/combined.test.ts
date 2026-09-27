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

import { combinedLines } from './combined.ts'

function numbers(count: number, edits: Record<number, string> = {}): string[] {
  return Array.from({ length: count }, (_, i) => `${edits[i + 1] ?? String(i + 1)}\n`)
}

describe('combinedLines', () => {
  it('has no hunk when the result matches every parent', () => {
    const lines = numbers(5)
    expect(combinedLines([lines, lines], lines, true)).toEqual([])
  })

  it('marks each parent column for a conflict resolution', () => {
    expect(
      combinedLines(
        [
          ['a\n', 'MAIN\n', 'c\n'],
          ['a\n', 'SIDE\n', 'c\n'],
        ],
        ['a\n', 'BOTH\n', 'c\n'],
        true,
      ),
    ).toEqual(['@@@ -1,3 -1,3 +1,3 @@@\n', '  a\n', '- MAIN\n', ' -SIDE\n', '++BOTH\n', '  c\n'])
  })

  it('drops a clean merge of distant edits only when dense', () => {
    const ours = numbers(20, { 8: 'eight' }),
      theirs = numbers(20, { 2: 'two' }),
      result = numbers(20, { 2: 'two', 8: 'eight' })
    expect(combinedLines([ours, theirs], result, true)).toEqual([])
    expect(combinedLines([ours, theirs], result, false)[0]).toBe('@@@ -1,11 -1,11 +1,11 @@@\n')
  })

  it('keeps edits from both sides within context when dense', () => {
    const ours = numbers(20, { 5: 'five' }),
      theirs = numbers(20, { 2: 'two' }),
      result = numbers(20, { 2: 'two', 5: 'five' })
    expect(combinedLines([ours, theirs], result, true)).toEqual([
      '@@@ -1,8 -1,8 +1,8 @@@\n',
      '  1\n',
      '- 2\n',
      '+ two\n',
      '  3\n',
      '  4\n',
      ' -5\n',
      ' +five\n',
      '  6\n',
      '  7\n',
      '  8\n',
    ])
  })

  it('numbers an empty side from one', () => {
    expect(combinedLines([[], []], ['new\n'], true)).toEqual([
      '@@@ -1,0 -1,0 +1,1 @@@\n',
      '++new\n',
    ])
    expect(combinedLines([['b\n'], ['b\n']], [], true)).toEqual([
      '@@@ -1,1 -1,1 +1,0 @@@\n',
      '--b\n',
    ])
  })

  it('carries function context in the header, less its last byte', () => {
    const lines = Array.from({ length: 20 }, (_, i) => `  body ${String(i + 1)}\n`)
    lines[4] = 'function handleRequest(request, response) {\n'
    const ours = [...lines],
      theirs = [...lines],
      result = [...lines]
    ours[14] = '  MAIN\n'
    theirs[14] = '  SIDE\n'
    result[14] = '  BOTH\n'
    expect(combinedLines([ours, theirs], result, true)[0]).toBe(
      '@@@ -12,7 -12,7 +12,7 @@@ function handleRequest(request, respons\n',
    )
  })

  it('adds no marker for a missing final newline', () => {
    const body = combinedLines(
      [
        ['x\n', 'MAIN'],
        ['x\n', 'SIDE'],
      ],
      ['x\n', 'BOTH'],
      true,
    )
    expect(body.slice(-3)).toEqual(['- MAIN\n', ' -SIDE\n', '++BOTH\n'])
  })
})

it('keeps a valid empty result range for a zero-context deletion', () => {
  expect(combinedLines([['gone\n'], ['gone\n']], [], true, 0)).toEqual([
    '@@@ -1,1 -1,1 +1,0 @@@\n',
    '--gone\n',
  ])
})
