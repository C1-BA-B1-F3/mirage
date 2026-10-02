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

import { RAM_COMMANDS } from './index.ts'
import { describe, expect, it } from 'vitest'
import { materialize } from '../../../io/types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { PathSpec } from '../../../types.ts'
const RAM_GREP = RAM_COMMANDS.filter((c) => c.name === 'grep' && c.filetype == null)

const ENC = new TextEncoder()
const DEC = new TextDecoder()

async function runGrep(
  vfs: RAMVFS,
  pattern: string,
  paths: PathSpec[],
  flags: Record<string, string | boolean | number | string[]> = {},
): Promise<{ text: string; exitCode: number }> {
  const cmd = RAM_GREP[0]
  if (cmd === undefined) throw new Error('grep not registered')
  const result = await cmd.fn(vfs.accessor, paths, [pattern], {
    stdin: null,
    flags,
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) return { text: '', exitCode: 0 }
  const [out, io] = result
  if (out === null) return { text: '', exitCode: io.exitCode }
  const buf = out instanceof Uint8Array ? out : await materialize(out as AsyncIterable<Uint8Array>)
  return { text: DEC.decode(buf), exitCode: io.exitCode }
}

describe('grep', () => {
  it('empty file returns no match', async () => {
    const vfs = new RAMVFS()
    vfs.store.files.set('/tmp/a.txt', new Uint8Array())
    const { text, exitCode } = await runGrep(vfs, 'hello', [PathSpec.fromStrPath('/tmp/a.txt')])
    expect(text).toBe('')
    expect(exitCode).toBe(1)
  })

  it('-r on a single file retains single-file output', async () => {
    const vfs = new RAMVFS()
    vfs.store.files.set('/log.txt', ENC.encode('one\nerror here\ntwo\nerror again\n'))
    const { text } = await runGrep(vfs, 'error', [PathSpec.fromStrPath('/log.txt')], {
      r: true,
      n: true,
    })
    expect(text).toBe('2:error here\n4:error again\n')
  })
})

// How the classifier hands over a typed stdin operand: `-` resolved under the
// cwd, /dev/stdin as the path it is, each spelled as typed.
function stdinOperand(raw: string): PathSpec {
  const virtual = raw === '/dev/stdin' ? '/dev/stdin' : '/-'
  return new PathSpec({
    virtual,
    directory: '/',
    vfsPath: virtual.slice(1),
    resolved: true,
    rawPath: raw,
  })
}

async function runOnStdin(
  paths: PathSpec[],
  texts: string[],
  flags: Record<string, string | boolean | number | string[]>,
): Promise<string> {
  const cmd = RAM_GREP[0]
  if (cmd === undefined) throw new Error('command not registered')
  const result = await cmd.fn(new RAMVFS().accessor, paths, texts, {
    stdin: ENC.encode('b\n'),
    flags,
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) return ''
  const [out] = result
  if (out === null) return ''
  return DEC.decode(
    out instanceof Uint8Array ? out : await materialize(out as AsyncIterable<Uint8Array>),
  )
}

// GNU grep 3.11 calls only `-` "(standard input)": /dev/stdin reads the same
// bytes and is named as the path it is.
describe('grep names only a dash stdin', () => {
  it.each([
    ['/dev/stdin', { H: true }, '/dev/stdin:b\n'],
    ['/dev/stdin', { args_l: true }, '/dev/stdin\n'],
    ['-', { H: true }, '(standard input):b\n'],
    ['-', { args_l: true }, '(standard input)\n'],
  ])('names %s under %j', async (raw, flags, want) => {
    expect(await runOnStdin([stdinOperand(raw)], ['b'], flags)).toBe(want)
  })
})
