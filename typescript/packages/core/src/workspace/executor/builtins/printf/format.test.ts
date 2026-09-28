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
import { encodeText } from '../../../../shell/bytes.ts'
import { runPrintf } from './format.ts'

// GNU pins taken in debian:stable-slim. `handlePrintf` collapses the
// error list into one stderr blob and a status, so the list itself —
// order and count — is only observable here. Mirrors python's
// tests/workspace/executor/builtins/printf/test_format.py.

// bash 5.2.37 through `od -An -tx1`: the format reads \NNN, one to three
// octal digits, and a %b argument also reads \0NNN, a leading 0 and up
// to three more.
const OCTAL_PINS: [string, string, string][] = [
  ['\\0003', '00 33', '03'],
  ['\\0', '00', '00'],
  ['\\00', '00', '00'],
  ['\\000', '00', '00'],
  ['\\0000', '00 30', '00'],
  ['\\08', '00 38', '00 38'],
  ['\\101', '41', '41'],
  ['\\1011', '41 31', '41 31'],
  ['\\0101', '08 31', '41'],
  ['\\400', '00', '00'],
  ['\\0400', '20 30', '00'],
]

// bash 5.2.37 under LC_ALL=C.UTF-8 through `od -An -tx1`: the format and
// a %b argument write \u and \U through u32toutf8, so a surrogate half
// and a value past Unicode come out UTF-8-shaped, and 0x80000000 and
// past come out as nothing.
const UNICODE_PINS: [string, string][] = [
  ['\\uD800', 'ed a0 80'],
  ['\\uDC80', 'ed b2 80'],
  ['\\uDFFF', 'ed bf bf'],
  ['\\uD83D\\uDE00', 'ed a0 bd ed b8 80'],
  ['\\U00110000', 'f4 90 80 80'],
  ['\\U0010FFFF', 'f4 8f bf bf'],
  ['\\U7FFFFFFF', 'fd bf bf bf bf bf'],
  ['\\U80000000', ''],
  ['\\UFFFFFFFF', ''],
  ['x\\UFFFFFFFFy', '78 79'],
  ['a\\u0000b', '61 00 62'],
  ['\\uDC80\\xff', 'ed b2 80 ff'],
]

function od(text: string): string {
  return Array.from(encodeText(text), (b) => b.toString(16).padStart(2, '0')).join(' ')
}

describe('runPrintf', () => {
  it('returns errors as a list in argument order', () => {
    const [out, errors] = runPrintf('%d %d\n', ['abc', 'def'])
    expect(out).toBe('0 0\n')
    expect(errors).toEqual(['printf: abc: invalid number\n', 'printf: def: invalid number\n'])
  })

  it('ends the reuse when a cycle consumes nothing', () => {
    // `a%%b` has no conversion, so the first cycle consumes no argument
    // and the excess args are dropped rather than looping forever.
    expect(runPrintf('a%%b\n', ['x', 'y', 'z'])).toEqual(['a%b\n', []])
  })

  it('drops every argument for an empty format', () => {
    expect(runPrintf('', ['a', 'b', 'c'])).toEqual(['', []])
  })

  it('suppresses the rest of the format after a stop from %b', () => {
    expect(runPrintf('[%b][%s]\n', ['ab\\ccd', 'tail'])).toEqual(['[ab', []])
  })

  it('ends every cycle when the stop lands on a later one', () => {
    expect(runPrintf('<%b>', ['one', 'tw\\co', 'three'])).toEqual(['<one><tw', []])
  })

  it.each([
    ['0.5', '0'],
    ['1.5', '2'],
    ['2.5', '2'],
    ['3.5', '4'],
  ])('rounds %s half-to-even at fixed precision', (value, expected) => {
    expect(runPrintf('%.0f', [value])).toEqual([expected, []])
  })

  it('renders a missing argument as the empty string or zero', () => {
    expect(runPrintf('[%s][%d]', [])).toEqual(['[][0]', []])
  })

  it.each(OCTAL_PINS)(
    'reads %s as three digits in the format and a zero plus three in %%b',
    (escape, inFormat, inBArg) => {
      const [fmtOut, fmtErrors] = runPrintf(escape, [])
      const [bOut, bErrors] = runPrintf('%b', [escape])
      expect([od(fmtOut), fmtErrors]).toEqual([inFormat, []])
      expect([od(bOut), bErrors]).toEqual([inBArg, []])
    },
  )

  it.each(UNICODE_PINS)(
    'writes %s through u32toutf8 in the format and in a %b argument',
    (escape, expected) => {
      const [fmtOut, fmtErrors] = runPrintf(escape, [])
      const [bOut, bErrors] = runPrintf('%b', [escape])
      expect([od(fmtOut), fmtErrors]).toEqual([expected, []])
      expect([od(bOut), bErrors]).toEqual([expected, []])
    },
  )
})
