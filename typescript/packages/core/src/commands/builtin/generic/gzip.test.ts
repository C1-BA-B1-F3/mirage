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
// Mirrors python/tests/commands/builtin/generic/test_gzip.py.

import { describe, expect, it } from 'vitest'
import { eacces } from '../../../utils/errors.ts'
import { gzipGeneric } from './gzip.ts'
import { gzip, gunzip } from '../../../utils/compress.ts'
import { MountMode, PathSpec } from '../../../types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'

async function shell(
  line: string,
  stdin: Uint8Array | null = null,
  seed: Record<string, string> = {},
): Promise<[string, string, number]> {
  const ws = new Workspace(
    { '/data/': new RAMVFS() },
    { mode: MountMode.WRITE, shellParser: await getTestParser() },
  )
  try {
    for (const [path, body] of Object.entries(seed)) {
      await ws.shell(`tee ${path} > /dev/null`, { stdin: new TextEncoder().encode(body) })
    }
    const io = await ws.shell(line, { stdin })
    const dec = new TextDecoder()
    return [dec.decode(io.stdout), dec.decode(io.stderr), io.exitCode]
  } finally {
    await ws.close()
  }
}

describe('gzip with a dash operand', () => {
  it('writes the dash to stdout while files compress in place', async () => {
    const r = await shell(
      'cd /data && gzip - a.txt | gzip -dc; ls',
      new TextEncoder().encode('hi\n'),
      {
        '/data/a.txt': 'file\n',
      },
    )
    expect(r).toEqual(['hi\na.txt.gz\n', '', 0])
  })
})

describe('gzip -d on inputs gzip refuses', () => {
  it('calls a truncated stdin an unexpected end', async () => {
    const cut = (await gzip(new TextEncoder().encode('hi\n'))).subarray(0, 10)
    expect(await shell('gzip -dc', cut)).toEqual(['', '\ngzip: stdin: unexpected end of file\n', 1])
  })
})

describe('gzip on a link in place (O_NOFOLLOW unless -c or -f)', () => {
  const seed = "cd /data && printf 'hello\\n' > a.txt && ln -s a.txt al && "
  it.each(['gzip al', 'gzip -k al', 'gzip -q al'])('%s refuses the link', async (line) => {
    const r = await shell(`${seed}${line}; ls -F`)
    expect(r).toEqual(['a.txt\nal@\n', 'gzip: al: Too many levels of symbolic links\n', 0])
  })

  it.each([
    ['gzip -f al', 'a.txt\nal.gz\n'],
    ['gzip -kf al', 'a.txt\nal@\nal.gz\n'],
  ])('%s compresses beside the link', async (line, listing) => {
    const r = await shell(`${seed}${line} && ls -F && gunzip -c al.gz`)
    expect(r).toEqual([`${listing}hello\n`, '', 0])
  })
})

it.each([false, true])('compression skips suffixes or reports late errors: %s', async (skipped) => {
  const reads: string[] = []
  const writes = new Map<string, Uint8Array>()
  const removed: string[] = []
  const name = skipped ? '/bad.gz' : '/bad'
  async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    reads.push(path.virtual)
    yield new TextEncoder().encode('hello\n')
    if (path.virtual === name) {
      reads.push('continued')
      throw eacces(path)
    }
  }
  const result = await gzipGeneric(
    [PathSpec.fromStrPath(name), PathSpec.fromStrPath('/good')],
    { flags: {}, stdin: null, filetypeFns: null, cwd: '/' },
    read,
    (path, data) => {
      writes.set(path.virtual, data)
      return Promise.resolve()
    },
    (path) => {
      removed.push(path.virtual)
      return Promise.resolve()
    },
  )
  if (result === null) throw new Error('gzip returned no result')
  const [, io] = result
  expect(io.exitCode).toBe(skipped ? 0 : 1)
  expect(await io.stderrStr()).toBe(
    skipped
      ? 'gzip: /bad.gz already has .gz suffix -- unchanged\n'
      : '\ngzip: /bad: Permission denied\n',
  )
  expect(reads).toEqual(skipped ? [name, '/good'] : [name, 'continued'])
  expect(removed).toEqual(skipped ? ['/good'] : [])
  expect([...writes.keys()]).toEqual(skipped ? ['/good.gz'] : [])
  if (skipped) {
    const output = writes.get('/good.gz')
    if (output === undefined) throw new Error('gzip did not write the next file')
    expect(await gunzip(output)).toEqual(new TextEncoder().encode('hello\n'))
  }
})
