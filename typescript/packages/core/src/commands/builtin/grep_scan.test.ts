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
import { IOResult } from '../../io/types.ts'
import { grepLines, type GrepLinesOptions } from './grep_scan.ts'

function lineOpts(overrides: Partial<GrepLinesOptions> = {}): GrepLinesOptions {
  return {
    invert: false,
    lineNumbers: false,
    countOnly: false,
    filesOnly: false,
    onlyMatching: true,
    maxCount: null,
    ...overrides,
  }
}

describe('grepLines -o GNU semantics', () => {
  it('prints nothing for an empty match yet counts the line', () => {
    expect(grepLines('/p', ['ab'], /[0-9]*/, lineOpts())).toEqual([])
    expect(grepLines('/p', ['ab'], /[0-9]*/, lineOpts({ countOnly: true }))).toEqual(['1'])
    expect(grepLines('/p', ['ab'], /[0-9]*/, lineOpts({ filesOnly: true }))).toEqual(['/p'])
  })

  it('prints every non-empty match on the line, one per entry', () => {
    expect(grepLines('/p', ['a1b'], /[0-9]*/, lineOpts())).toEqual(['1'])
    expect(grepLines('/p', ['a1b2c'], /[0-9]/, lineOpts())).toEqual(['1', '2'])
    expect(grepLines('/p', ['1a22b'], /[0-9]*/, lineOpts())).toEqual(['1', '22'])
    expect(grepLines('/p', ['abc'], /b*/, lineOpts())).toEqual(['b'])
  })

  it('numbers every match of the line it came from', () => {
    expect(grepLines('/p', ['x', 'a1b2c'], /[0-9]/, lineOpts({ lineNumbers: true }))).toEqual([
      '2:1',
      '2:2',
    ])
  })
})

describe('-b through the select path', () => {
  // The byte layout is section Q1 of the GNU truth file (GNU grep 3.11).
  const F1 = ['abc', 'defabc', 'abc abc']

  it('prints the line start offset', () => {
    const opts = lineOpts({ onlyMatching: false, byteOffsets: true })
    expect(grepLines('/p', F1, /abc/, opts)).toEqual(['0:abc', '4:defabc', '11:abc abc'])
  })

  it('prints the match offset under -o', () => {
    expect(grepLines('/p', F1, /abc/, lineOpts({ byteOffsets: true }))).toEqual([
      '0:abc',
      '7:abc',
      '11:abc',
      '15:abc',
    ])
  })

  it('keeps GNU field order whatever the flags', () => {
    expect(
      grepLines(
        '/p',
        ['abc', 'defabc'],
        /abc/,
        lineOpts({ onlyMatching: false, lineNumbers: true, byteOffsets: true }),
      ),
    ).toEqual(['1:0:abc', '2:4:defabc'])
  })

  it('counts bytes rather than characters', () => {
    // `caf` + U+00E9 (two bytes) + a space is six bytes.
    expect(
      grepLines('/p', ['café abc', 'xéy abc'], /abc/, lineOpts({ byteOffsets: true })),
    ).toEqual(['6:abc', '15:abc'])
  })

  it('leaves a count and a file list alone', () => {
    expect(grepLines('/p', F1, /abc/, lineOpts({ countOnly: true, byteOffsets: true }))).toEqual([
      '3',
    ])
    expect(grepLines('/p', F1, /abc/, lineOpts({ filesOnly: true, byteOffsets: true }))).toEqual([
      '/p',
    ])
  })

  it('prints the offsets of the lines -v selected', () => {
    expect(
      grepLines(
        '/p',
        ['one', 'two abc', 'three', 'four abc', 'five'],
        /abc/,
        lineOpts({ onlyMatching: false, invert: true, byteOffsets: true }),
      ),
    ).toEqual(['0:one', '12:three', '27:five'])
  })
})

describe('-m 0 selects nothing', () => {
  // Measured on GNU grep 3.11: `grep -m0 a f`, `grep -m0 -c a f`,
  // `grep -m0 -v a f` and `grep -m0 -l a f` all print zero bytes and exit 1.
  // Reading the limit only after a line was printed let the first selected
  // line out first, because `count >= 0` is already true.
  it('prints no line', () => {
    expect(grepLines('/f.txt', ['a', 'ab', 'b'], /a/, lineOpts({ maxCount: 0 }))).toEqual([])
  })

  it('counts nothing', () => {
    // Not `['0']`: a caller renders `<file>:<count>` from whatever comes
    // back, and GNU prints no per-file zeros under -m0.
    expect(
      grepLines('/f.txt', ['a', 'ab', 'b'], /a/, lineOpts({ maxCount: 0, countOnly: true })),
    ).toEqual([])
  })

  it('names no file', () => {
    expect(
      grepLines('/f.txt', ['a', 'ab', 'b'], /a/, lineOpts({ maxCount: 0, filesOnly: true })),
    ).toEqual([])
  })

  it('reports no selection', () => {
    const io = new IOResult({ exitCode: 1 })
    grepLines('/f.txt', ['a', 'ab', 'b'], /a/, lineOpts({ maxCount: 0, io }))
    expect(io.exitCode).toBe(1)
  })
})

describe('-o -v prints nothing', () => {
  // Measured on GNU grep 3.11 over `abc\ndef\n`: `grep -ov abc` is zero bytes
  // and exit 0, `grep -ovc abc` is `1`, and `grep -ovl abc` names the file.
  // ripgrep prints the whole line instead; GNU is the reference the rest of
  // this family already follows for -o.
  it('prints no line', () => {
    expect(grepLines('/f.txt', ['abc', 'def'], /abc/, lineOpts({ invert: true }))).toEqual([])
  })

  it('still counts the selected line', () => {
    expect(
      grepLines('/f.txt', ['abc', 'def'], /abc/, lineOpts({ invert: true, countOnly: true })),
    ).toEqual(['1'])
  })

  it('still names the file', () => {
    expect(
      grepLines('/f.txt', ['abc', 'def'], /abc/, lineOpts({ invert: true, filesOnly: true })),
    ).toEqual(['/f.txt'])
  })

  it('still reports selection', () => {
    const io = new IOResult({ exitCode: 1 })
    grepLines('/f.txt', ['abc', 'def'], /abc/, lineOpts({ invert: true, io }))
    expect(io.exitCode).toBe(0)
  })
})

describe('offsets over a smuggled byte', () => {
  // `grep -bo a` over `\xffa\n` is `1:a` on GNU grep 3.11, and `grep -b a`
  // over `\xff\na\n` is `2:a`. A replacing decode read the invalid byte as
  // U+FFFD, three bytes wide, so both answers ran ahead.
  it('counts one byte in a list-returning scan', () => {
    expect(grepLines('/f.txt', ['\udcffa'], /a/, lineOpts({ byteOffsets: true }))).toEqual(['1:a'])
  })

  it('keeps a smuggled byte on the way out of a list-returning scan', () => {
    // A list-returning scan hands its lines to `formatRecords`, which puts a
    // sentinel back as the byte it stands for, so the line keeps it: GNU
    // grep and ripgrep both print the byte raw.
    expect(
      grepLines('/f.txt', ['\udcffa'], /a/, lineOpts({ onlyMatching: false, byteOffsets: true })),
    ).toEqual(['0:\udcffa'])
  })
})
