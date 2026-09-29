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

// Mirrors python/tests/commands/builtin/generic/crossmount/relay/test_wc.py.

import { expect, it } from 'vitest'
import { IOResult, materialize } from '../../../../../io/types.ts'
import { FileStat, FileType, PathSpec } from '../../../../../types.ts'
import type { FlagValue } from '../../../../spec/types.ts'
import { enoent } from '../../../../../utils/errors.ts'
import type { CrossResult } from '../types.ts'
import { parseRow, runWc } from './wc.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

// What each operand's own mount answers for `wc -l`, and what stat says.
const ROWS: Record<string, [string, string | null]> = {
  '/a/dir': ['0 /a/dir\n', 'wc: /a/dir: Is a directory\n'],
  '/b/name with spaces': ['1 /b/name with spaces\n', null],
  '/b/x': ['1 /b/x\n', null],
  '/pg/rows': ['5 /pg/rows\n', null],
  '/pg2/rows': ['3 /pg2/rows\n', null],
  '/a/n\nq': ['2 /a/n\nq\n', null],
  '/gone': ['4 /gone\n', null],
}
const SIZES: Record<string, number | null> = {
  '/b/name with spaces': 6,
  '/b/x': 120,
  '/a/n\nq': 4,
}

class Mounts {
  runs: [string, string[], Record<string, FlagValue>][] = []
  ops: string[] = []

  runSingle = (
    name: string,
    paths: PathSpec[],
    _texts: string[],
    flags: Record<string, FlagValue>,
  ): Promise<CrossResult> => {
    this.runs.push([name, paths.map((p) => p.virtual), flags])
    const [out, err] = ROWS[paths[0]?.virtual ?? ''] ?? ['', null]
    return Promise.resolve([
      ENC.encode(out),
      new IOResult({
        exitCode: err === null ? 0 : 1,
        stderr: err === null ? null : ENC.encode(err),
      }),
    ])
  }

  dispatch = (op: string, path: PathSpec): Promise<[unknown, IOResult]> => {
    this.ops.push(op)
    if (path.virtual === '/gone') return Promise.reject(enoent(path))
    const type = path.virtual === '/a/dir' ? FileType.DIRECTORY : FileType.FILE
    const stat = new FileStat({ name: path.virtual, type, size: SIZES[path.virtual] ?? null })
    return Promise.resolve([stat, new IOResult()])
  }
}

function specs(...paths: string[]): PathSpec[] {
  return paths.map((p) => PathSpec.fromStrPath(p))
}

it.each([
  [{ lines: true }, '      0 /a/dir\n      1 /b/name with spaces\n      1 total\n'],
  [{ lines: true, total: 'only' }, '1\n'],
  [{ lines: true, total: 'never' }, '      0 /a/dir\n      1 /b/name with spaces\n'],
] as [Record<string, FlagValue>, string][])(
  'each mount counts its operand: %j',
  async (flags, expected) => {
    const mounts = new Mounts()
    const [body, io] = await runWc(
      specs('/a/dir', '/b/name with spaces'),
      flags,
      mounts.dispatch,
      mounts.runSingle,
    )
    expect(DEC.decode(await materialize(body))).toBe(expected)
    expect(mounts.runs).toEqual([
      ['wc', ['/a/dir'], { ...flags, total: 'never' }],
      ['wc', ['/b/name with spaces'], { ...flags, total: 'never' }],
    ])
    expect(mounts.ops).not.toContain('read')
    expect(io.exitCode).toBe(1)
    expect(DEC.decode(await materialize(io.stderr))).toBe('wc: /a/dir: Is a directory\n')
  },
)

it.each([
  [['/pg/rows', '/pg2/rows'], '5 /pg/rows\n3 /pg2/rows\n8 total\n'],
  [['/pg/rows', '/b/x'], '  5 /pg/rows\n  1 /b/x\n  6 total\n'],
])('an unsized file pads to its count: %j', async (paths, expected) => {
  const mounts = new Mounts()
  const [body, io] = await runWc(
    specs(...paths),
    { lines: true },
    mounts.dispatch,
    mounts.runSingle,
  )
  expect(DEC.decode(await materialize(body))).toBe(expected)
  expect(io.exitCode).toBe(0)
})

it('reads a name holding a newline as one quoted row', async () => {
  // One operand's run is one row, whatever its name holds; the report quotes
  // that name as GNU wc does, so no row spans two lines.
  const mounts = new Mounts()
  const [body] = await runWc(
    specs('/a/n\nq', '/b/x'),
    { lines: true },
    mounts.dispatch,
    mounts.runSingle,
  )
  expect(DEC.decode(await materialize(body))).toBe("  2 '/a/n'$'\\n''q'\n  1 /b/x\n  3 total\n")
})

it('keeps every count when a file is gone before sizing', async () => {
  const mounts = new Mounts()
  const [body, io] = await runWc(
    specs('/gone', '/b/x'),
    { lines: true },
    mounts.dispatch,
    mounts.runSingle,
  )
  expect(DEC.decode(await materialize(body))).toBe('  4 /gone\n  1 /b/x\n  5 total\n')
  expect(io.exitCode).toBe(0)
})

it('rejects an invalid total before any mount runs', async () => {
  const mounts = new Mounts()
  const [, io] = await runWc(
    specs('/a/x', '/b/x'),
    { total: 'bogus' },
    mounts.dispatch,
    mounts.runSingle,
  )
  expect(io.exitCode).toBe(1)
  expect(DEC.decode(await materialize(io.stderr))).toContain("invalid argument 'bogus'")
  expect(mounts.runs).toEqual([])
  expect(mounts.ops).toEqual([])
})

it.each([
  ['5   x', 1, { values: [5], label: '  x' }],
  ['  5  57 447 /m/d', 3, { values: [5, 57, 447], label: '/m/d' }],
  ['      8', 1, { values: [8], label: null }],
] as [string, number, { values: number[]; label: string | null }][])(
  'parseRow keeps the label whole: %j',
  (line, counts, expected) => {
    expect(parseRow(line, counts)).toEqual(expected)
  },
)
