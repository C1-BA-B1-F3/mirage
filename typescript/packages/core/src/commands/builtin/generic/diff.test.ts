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
// diff's stdin operands and as-typed names, pinned on GNU diffutils 3.10.
// Mirrors python/tests/commands/builtin/generic/test_diff.py.

import { describe, expect, it } from 'vitest'
import { diffGeneric } from './diff.ts'
import { UsageError } from '../../errors.ts'
import { materialize } from '../../../io/types.ts'
import { FileStat, FileType, PathSpec } from '../../../types.ts'
import type { CommandOpts } from '../../config.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

function operand(raw: string, virtual: string): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath: virtual.slice(3), rawPath: raw })
}

const DASH = operand('-', '/d/-')
const DEV_STDIN = new PathSpec({ virtual: '/dev/stdin', directory: '/dev', vfsPath: 'stdin' })
const FILE = operand('a.txt', '/d/a.txt')
const SUB = operand('sub', '/d/sub')
const SUB2 = operand('sub2', '/d/sub2')
const FILES: Record<string, string> = {
  '/d/a.txt': 'hello\n',
  '/d/sub/x': '1\n',
  '/d/sub2/x': '2\n',
  '/d/sub2/y': '3\n',
}
const DIRS: Record<string, string[]> = { '/d/sub': ['x'], '/d/sub2': ['x', 'y'] }

function read(p: PathSpec): AsyncIterable<Uint8Array> {
  return (async function* gen() {
    await Promise.resolve()
    yield ENC.encode(FILES[p.virtual] ?? '')
  })()
}

function readdir(p: PathSpec): Promise<string[]> {
  return Promise.resolve(DIRS[p.virtual] ?? [])
}

function stat(p: PathSpec): Promise<FileStat> {
  const type = p.virtual in DIRS ? FileType.DIRECTORY : FileType.FILE
  return Promise.resolve(new FileStat({ name: p.virtual.split('/').pop() ?? '', type }))
}

async function run(
  paths: PathSpec[],
  stdin: string | null = null,
  flags: Record<string, boolean> = {},
): Promise<[string, string, number]> {
  const opts = {
    flags,
    stdin: stdin === null ? null : ENC.encode(stdin),
  } as unknown as CommandOpts
  const [out, io] = await diffGeneric(paths, opts, read, readdir, stat)
  return [DEC.decode(await materialize(out)), DEC.decode(await materialize(io.stderr)), io.exitCode]
}

describe('diffGeneric with stdin', () => {
  it('reads a dash operand from stdin and names it dash', async () => {
    expect(await run([DASH, FILE], 'x\n', { q: true })).toEqual([
      'Files - and a.txt differ\n',
      '',
      1,
    ])
  })

  it('names the operands as typed in unified headers', async () => {
    const [out, , code] = await run([FILE, DEV_STDIN], 'x\n', { u: true })
    expect(out.startsWith('--- a.txt\n+++ /dev/stdin\n')).toBe(true)
    expect(code).toBe(1)
  })

  it('takes two stdin operands as one file', async () => {
    const unread = (p: PathSpec): AsyncIterable<Uint8Array> => {
      throw new Error(`read ${p.virtual}`)
    }
    const opts = { flags: {}, stdin: ENC.encode('abc') } as unknown as CommandOpts
    const [out, io] = await diffGeneric([DASH, DEV_STDIN], opts, unread, readdir, stat)
    expect([out, io.exitCode]).toEqual([null, 0])
  })

  it.each([
    [DASH, SUB],
    [SUB, DASH],
  ])('refuses a dash against a directory', async (a, b) => {
    expect(await run([a, b], 'x\n')).toEqual(['', "diff: cannot compare '-' to a directory\n", 2])
  })

  it("refuses a lone operand with GNU's missing operand usage error", async () => {
    const call = run([FILE])
    await expect(call).rejects.toThrow(
      new UsageError(
        "diff: missing operand after 'a.txt'\ndiff: Try 'diff --help' for more information.",
      ),
    )
    await expect(call).rejects.toMatchObject({ exitCode: 2 })
  })

  it('names recursive children under the typed operands', async () => {
    expect(await run([SUB, SUB2], null, { r: true })).toEqual([
      'diff -r sub/x sub2/x\n1c1\n< 1\n---\n> 2\nOnly in sub2: y\n',
      '',
      1,
    ])
  })
})
