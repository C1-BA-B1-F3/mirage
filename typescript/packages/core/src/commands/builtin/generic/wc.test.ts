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

import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { eisdir } from '../../../utils/errors.ts'
import type { CommandOpts } from '../../config.ts'
import { formatWcLines, numberWidth, parseFlags, wcGeneric } from './wc.ts'

// GNU's ARGMATCH refusal names the refused word through gnulib's quote(),
// so a byte outside 0x20-0x7e comes back escaped rather than interpolated
// raw. Every row measured against GNU coreutils 9.4 under `LC_ALL=C` with a
// raw `bytes` argv (`wc --total=<w>`). Mirrors test_wc.py.
describe('wc quotes the word --total refuses', () => {
  it.each([
    ['xé', 'x\\303\\251'],
    ['x\r', 'x\\r'],
    ['x\x01', 'x\\001'],
    ['x\x7f', 'x\\177'],
    ["x'", "x\\'"],
    ['x\\', 'x\\\\'],
  ])('escapes %j in the --total clause', (value, escaped) => {
    const message = parseFlags({ total: value })
    expect(typeof message === 'string' ? message.split('\n')[0] : message).toBe(
      `wc: invalid argument '${escaped}' for '--total'`,
    )
  })
})

// Measured, coreutils 9.4: `wc --total=x f` lists all four modes and adds
// the Try-help line. `--total=` is NOT the default -- GNU reads the empty
// word as a prefix of every candidate and answers `ambiguous argument ''`,
// which python used to take as `auto` and exit 0. Mirrors test_wc.py.
describe('wc --total refusal carries GNU candidate block', () => {
  it('lists the candidates', () => {
    expect(parseFlags({ total: 'x' })).toBe(
      "wc: invalid argument 'x' for '--total'\n" +
        "Valid arguments are:\n  - 'auto'\n  - 'always'\n  - 'only'\n  - 'never'\n" +
        "Try 'wc --help' for more information.\n",
    )
  })

  it('words an empty value as ambiguous', () => {
    const message = parseFlags({ total: '' })
    expect(typeof message === 'string' ? message.split('\n')[0] : message).toBe(
      "wc: ambiguous argument '' for '--total'",
    )
  })

  // `wc --total=al` is `always` and `=au` is `auto` (measured, coreutils
  // 9.4), while the bare `a` they share spans two values. Mirrors
  // test_wc.py.
  it.each([
    ['al', 'always'],
    ['au', 'auto'],
    ['o', 'only'],
    ['n', 'never'],
    ['always', 'always'],
  ])('resolves the unambiguous prefix %s', (value, total) => {
    const parsed = parseFlags({ total: value })
    expect(typeof parsed === 'string' ? parsed : parsed.total).toBe(total)
  })

  it('refuses a prefix spanning two values', () => {
    expect(parseFlags({ total: 'a' })).toBe(
      "wc: ambiguous argument 'a' for '--total'\n" +
        "Valid arguments are:\n  - 'auto'\n  - 'always'\n  - 'only'\n  - 'never'\n" +
        "Try 'wc --help' for more information.\n",
    )
  })

  it('still defaults an absent --total to auto', () => {
    const parsed = parseFlags({})
    expect(typeof parsed === 'string' ? parsed : parsed.total).toBe('auto')
  })
})

describe('formatWcLines', () => {
  it('quotes only a name holding a newline', () => {
    // coreutils 9.7 wc.c: `strchr (file, '\n') ? quotef (file) : file`.
    expect(formatWcLines([{ values: [2], label: '/a/n\nq' }])).toEqual(["2 '/a/n'$'\\n''q'"])
    expect(formatWcLines([{ values: [2], label: '/a/b c' }])).toEqual(['2 /a/b c'])
  })
})

describe('numberWidth', () => {
  // coreutils 9.7: one operand with one count is unpadded; otherwise the
  // regular files' total size, at least 7 beside a stream or directory.
  it.each([
    [[24], 1, 1, 1],
    [[24], 1, 3, 2],
    [[24, 6], 2, 1, 2],
    [[0, 0], 2, 3, 1],
    [[null], 1, 3, 7],
    [[null], 1, 1, 1],
    [[null, 24], 2, 1, 7],
    [[123456789], 2, 1, 9],
  ] as const)('sizes %j over %i operands and %i counts as %i', (sizes, operands, counts, width) => {
    expect(numberWidth(sizes, operands, counts)).toBe(width)
  })
})

describe('wcGeneric widths', () => {
  const files: Record<string, string> = { '/a.txt': 'hello\nworld\nfoo\nbar\nbaz\n' }
  const stream = (p: PathSpec): AsyncIterable<Uint8Array> =>
    (async function* gen() {
      await Promise.resolve()
      if (p.virtual === '/sub') throw eisdir('/sub')
      yield new TextEncoder().encode(files[p.virtual] ?? '')
    })()
  const run = async (
    paths: string[],
    flags: Record<string, boolean> = {},
  ): Promise<[string, string]> => {
    const opts = { flags, stdin: null } as unknown as CommandOpts
    const result = await wcGeneric(
      paths.map((p) => PathSpec.fromStrPath(p)),
      [],
      opts,
      stream,
    )
    if (result === null) throw new Error('wc returned nothing')
    const [out, io] = result
    const dec = new TextDecoder()
    return [dec.decode(await materialize(out)), dec.decode(await materialize(io.stderr))]
  }

  it('sizes the columns by the files', async () => {
    expect(await run(['/a.txt'], { lines: true, words: true })).toEqual([' 5  5 /a.txt\n', ''])
  })

  it('prints zeros for a directory and pads to seven', async () => {
    expect(await run(['/sub', '/a.txt'], { lines: true })).toEqual([
      '      0 /sub\n      5 /a.txt\n      5 total\n',
      'wc: /sub: Is a directory\n',
    ])
  })
})
