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

import { yieldBytes } from '../../../io/stream.ts'
import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { eisdir } from '../../../utils/errors.ts'
import type { CommandOpts } from '../../config.ts'
import { sedGeneric } from './sed.ts'

const DEC = new TextDecoder()

function latin1Bytes(text: string): number[] {
  return Array.from({ length: text.length }, (_, i) => text.charCodeAt(i))
}

async function sedBytes(
  paths: PathSpec[],
  texts: string[],
  flags: CommandOpts['flags'],
  files: Map<string, Uint8Array>,
  stdin: Uint8Array | null = null,
): Promise<number[] | null> {
  const opts = {
    stdin,
    flags,
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const result = await sedGeneric(
    paths,
    texts,
    opts,
    (p) => {
      const data = files.get(p.virtual)
      if (data === undefined) throw new Error(`no file ${p.virtual}`)
      return yieldBytes(data)
    },
    (p, data) => {
      files.set(p.virtual, data)
      return Promise.resolve()
    },
  )
  const out = result?.[0] ?? null
  return out === null ? null : [...(await materialize(out))]
}

async function runSed(
  texts: string[],
  flags: CommandOpts['flags'] = {},
  stdin: Uint8Array | null = null,
): Promise<{ exitCode: number; stderr: string }> {
  const opts = {
    stdin,
    flags,
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const result = await sedGeneric(
    [],
    texts,
    opts,
    () => {
      throw new Error('no operands; nothing to stream')
    },
    () => Promise.resolve(),
  )
  if (result === null) throw new Error('sed returned nothing')
  const io = result[1]
  const stderr = io.stderr === null ? '' : DEC.decode(await materialize(io.stderr))
  return { exitCode: io.exitCode, stderr }
}

describe('sed usage reporting', () => {
  it('names a missing script and exits 1', async () => {
    // GNU answers this with its whole usage block, also exit 1. Python used
    // to raise ValueError('sed: usage: sed EXPRESSION [path]') here.
    expect(await runSed([])).toEqual({ exitCode: 1, stderr: 'sed: missing script\n' })
  })

  it('reports no input files with GNU exit 4 when there is nothing to read', async () => {
    // GNU's spelling and exit code for `sed -i` with no operands; mirage
    // reuses them when there is no stdin either, having no terminal to
    // read. This used to be 'sed: missing operand' with exit 1 here and
    // ValueError('sed: usage: sed EXPRESSION path') in Python.
    expect(await runSed(['s/a/b/'])).toEqual({ exitCode: 4, stderr: 'sed: no input files\n' })
  })

  it('reports no input files for -i with no operands too', async () => {
    expect(await runSed(['s/a/b/'], { i: true })).toEqual({
      exitCode: 4,
      stderr: 'sed: no input files\n',
    })
  })
})

describe('sed text escapes above ASCII', () => {
  it('writes them as raw bytes', async () => {
    const out = await sedBytes(
      [],
      ['1a [\\xff][\\d200][\\o377][\\x80][\\xc3\\xa9][\\o400]\n2i [\\xe9]\n2c [\\d233][\\o351]'],
      {},
      new Map(),
      new TextEncoder().encode('x\ny\n'),
    )
    expect(out).toEqual(
      latin1Bytes('x\n[\xff][\xc8][\xff][\x80][\xc3\xa9][\x00]\n[\xe9]\n[\xe9][\xe9]\n'),
    )
  })

  it('writes a raw byte in place', async () => {
    const files = new Map([['/a.txt', new TextEncoder().encode('x\n')]])
    await sedBytes([PathSpec.fromStrPath('/a.txt')], ['a y\\xff'], { i: true }, files)
    expect([...(files.get('/a.txt') ?? [])]).toEqual(latin1Bytes('x\ny\xff\n'))
  })
})

describe('sed script files across -i files (GNU sed 4.9)', () => {
  const enc = (text: string): Uint8Array => new TextEncoder().encode(text)
  const text = (files: Map<string, Uint8Array>, name: string): string =>
    new TextDecoder().decode(files.get(name))

  it('reads an r file at each append, so an earlier edit shows', async () => {
    const files = new Map([
      ['/f', enc('one\ntwo\n')],
      ['/b', enc('b1\nb2\n')],
    ])
    const paths = [PathSpec.fromStrPath('/f'), PathSpec.fromStrPath('/b')]
    await sedBytes(paths, ['1r /f'], { i: true }, files)
    expect(text(files, '/f')).toBe('one\none\ntwo\ntwo\n')
    expect(text(files, '/b')).toBe('b1\none\none\ntwo\ntwo\nb2\n')
  })

  it('reads an R file as it was when the script was compiled', async () => {
    const files = new Map([
      ['/f', enc('one\ntwo\n')],
      ['/b', enc('b1\nb2\n')],
    ])
    const paths = [PathSpec.fromStrPath('/f'), PathSpec.fromStrPath('/b')]
    await sedBytes(paths, ['R /f'], { i: true }, files)
    expect(text(files, '/b')).toBe('b1\none\nb2\ntwo\n')
  })

  it('lets -i keep a w file it then edited', async () => {
    const files = new Map([
      ['/b', enc('b1\nb2\n')],
      ['/f', enc('old\n')],
    ])
    const paths = [PathSpec.fromStrPath('/b'), PathSpec.fromStrPath('/f')]
    await sedBytes(paths, ['s/b/B/;w /f'], { i: true }, files)
    expect(text(files, '/f')).toBe('')
    expect(text(files, '/b')).toBe('B1\nB2\n')
  })
})

describe('sed operands after a directory (GNU sed 4.9)', () => {
  const enc = (text: string): Uint8Array => new TextEncoder().encode(text)

  async function run(script: string): Promise<{ out: string; code: number; reads: string[] }> {
    const files = new Map([
      ['/f', enc('one\ntwo\n')],
      ['/g', enc('x\n')],
    ])
    const reads: string[] = []
    const paths = ['/f', '/d', '/g'].map((p) => PathSpec.fromStrPath(p))
    const opts = {
      stdin: null,
      flags: { n: true },
      filetypeFns: null,
      cwd: '/',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const result = await sedGeneric(
      paths,
      [script],
      opts,
      (p) => {
        reads.push(p.virtual)
        if (p.virtual === '/d') throw eisdir(p)
        return yieldBytes(files.get(p.virtual) ?? new Uint8Array())
      },
      () => Promise.resolve(),
    )
    if (result === null) throw new Error('sed returned nothing')
    const out = result[0] === null ? '' : DEC.decode(await materialize(result[0]))
    return { out, code: result[1].exitCode, reads }
  }

  it('reads past the directory when a $ looks ahead', async () => {
    expect(await run('$p')).toEqual({ out: 'x\n', code: 0, reads: ['/f', '/d', '/g'] })
  })

  it('reads nothing past the directory without a $', async () => {
    expect(await run('p')).toEqual({ out: 'one\ntwo\n', code: 4, reads: ['/f', '/d'] })
  })
})
