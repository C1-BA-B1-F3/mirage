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
// Mirrors python/tests/commands/builtin/generic/test_gunzip.py.

import { describe, expect, it } from 'vitest'
import { gzip } from '../../../utils/compress.ts'
import { MountMode } from '../../../types.ts'
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

describe('gunzip with a dash operand', () => {
  it('writes the dash to stdout while files decompress in place', async () => {
    const r = await shell(
      'cd /data && gzip b.txt && gunzip - b.txt.gz; ls; cat b.txt',
      await gzip(new TextEncoder().encode('hi\n')),
      { '/data/b.txt': 'file\n' },
    )
    expect(r).toEqual(['hi\nb.txt\nfile\n', '', 0])
  })
})

describe('gunzip on inputs gzip refuses', () => {
  it('reports a plain file and leaves it in place', async () => {
    const r = await shell('cd /data && gzip b.txt && gunzip p.gz b.txt.gz; ls', null, {
      '/data/b.txt': 'file\n',
      '/data/p.gz': 'plain\n',
    })
    expect(r).toEqual(['b.txt\np.gz\n', '\ngzip: p.gz: not in gzip format\n', 0])
  })

  it('calls plain stdin not in gzip format', async () => {
    const r = await shell('gunzip', new TextEncoder().encode('hello\n'))
    expect(r).toEqual(['', '\ngzip: stdin: not in gzip format\n', 1])
  })
})

// gzip -n of "hello\n" with its CRC-32 and length trailer zeroed.
const HELLO = [
  0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 3, 0xcb, 0x48, 0xcd, 0xc9, 0xc9, 0xe7, 2, 0, 0x20, 0x30, 0x3a,
  0x36, 6, 0, 0, 0,
]
const DAMAGED = new Uint8Array([...HELLO.slice(0, -8), 0, 0, 0, 0, 0, 0, 0, 0])

describe('gunzip on a damaged member', () => {
  it('keeps the inflated bytes before the trailer errors', async () => {
    const ws = new Workspace(
      { '/data/': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    try {
      await ws.shell('tee /data/bad.gz > /dev/null', { stdin: DAMAGED })
      await ws.shell('tee /data/ok.gz > /dev/null', {
        stdin: await gzip(new TextEncoder().encode('x\n')),
      })
      const io = await ws.shell('gunzip -c /data/bad.gz /data/ok.gz')
      const dec = new TextDecoder()
      expect([dec.decode(io.stdout), dec.decode(io.stderr), io.exitCode]).toEqual([
        'hello\n',
        '\ngzip: /data/bad.gz: invalid compressed data--crc error\n' +
          '\ngzip: /data/bad.gz: invalid compressed data--length error\n',
        1,
      ])
    } finally {
      await ws.close()
    }
  })

  it('keeps the members before a later bad header', async () => {
    const ws = new Workspace(
      { '/data/': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    try {
      const bad = [...HELLO.slice(0, 2), 7, ...HELLO.slice(3)]
      await ws.shell('tee /data/two.gz > /dev/null', { stdin: new Uint8Array([...HELLO, ...bad]) })
      const io = await ws.shell('cd /data && gunzip two.gz; ls; cat two')
      const dec = new TextDecoder()
      expect([dec.decode(io.stdout), dec.decode(io.stderr)]).toEqual([
        'two\nhello\n',
        'gzip: two.gz: unknown method 7 -- not supported\n',
      ])
    } finally {
      await ws.close()
    }
  })
})

// Run `line` in /data beside t.gz and a link tl.gz naming it, with a
// read-only /ro holding f.gz, as gzip 1.13 was pinned.
async function linked(line: string): Promise<[Workspace, string, string, number]> {
  const ro = new RAMVFS()
  const seed = new Workspace(
    { '/ro/': ro },
    { mode: MountMode.WRITE, shellParser: await getTestParser() },
  )
  await seed.shell('tee /ro/f.gz > /dev/null', {
    stdin: await gzip(new TextEncoder().encode('ro\n')),
  })
  const ws = new Workspace(
    { '/data/': new RAMVFS(), '/ro/': [ro, MountMode.READ] },
    { mode: MountMode.WRITE, shellParser: await getTestParser() },
  )
  await ws.shell('tee /data/t.gz > /dev/null', {
    stdin: await gzip(new TextEncoder().encode('hello\n')),
  })
  await ws.shell('mkdir /data/dir && cd /data && ln -s t.gz tl.gz')
  const io = await ws.shell(`cd /data && ${line}`)
  const dec = new TextDecoder()
  return [ws, dec.decode(io.stdout), dec.decode(io.stderr), io.exitCode]
}

async function out(ws: Workspace, line: string): Promise<string> {
  return new TextDecoder().decode((await ws.shell(line)).stdout)
}

describe('gunzip on a link in place (O_NOFOLLOW unless -c or -f)', () => {
  it.each([
    ['gunzip tl.gz', 'gzip: tl.gz: Too many levels of symbolic links\n'],
    ['gunzip -k -q tl.gz', 'gzip: tl.gz: Too many levels of symbolic links\n'],
    ['gzip -d tl.gz', 'gzip: tl.gz: Too many levels of symbolic links\n'],
    ['ln -s nowhere d.gz && gunzip d.gz', 'gzip: d.gz: Too many levels of symbolic links\n'],
    ['ln -s dir dl && gunzip dl', 'gzip: dl: Too many levels of symbolic links\n'],
    ['ln -s t.gz x.gz && gunzip x', 'gzip: x.gz: Too many levels of symbolic links\n'],
  ])('%s refuses the link', async (line, err) => {
    const [ws, , stderr, code] = await linked(line)
    expect([stderr, code]).toEqual([err, 1])
    expect(await out(ws, 'ls /data')).toContain('t.gz')
    await ws.close()
  })

  it('decodes beside the link under -f and removes the link', async () => {
    const [ws, , stderr, code] = await linked('gunzip -f tl.gz')
    expect([stderr, code]).toEqual(['', 0])
    expect(await out(ws, 'cd /data && ls -F && cat tl')).toBe('dir/\nt.gz\ntl\nhello\n')
    await ws.close()
  })

  it('keeps the link under -k -f', async () => {
    const [ws, , , code] = await linked('gunzip -kf tl.gz')
    expect(code).toBe(0)
    expect(await out(ws, 'cd /data && ls -F')).toBe('dir/\nt.gz\ntl\ntl.gz@\n')
    await ws.close()
  })

  it('follows -c and a retried link through the door', async () => {
    const [ws, stdout, , code] = await linked('ln -s t.gz x.gz && gunzip -c tl.gz x')
    expect([stdout, code]).toEqual(['hello\nhello\n', 0])
    await ws.close()
  })

  it('writes beside a link into a read-only mount', async () => {
    const [ws, , stderr, code] = await linked('ln -s /ro/f.gz rl.gz && gunzip -f rl')
    expect([stderr, code]).toEqual(['', 0])
    expect(await out(ws, 'cat /data/rl && ls /ro')).toBe('ro\nf.gz\n')
    await ws.close()
  })

  it('counts a link at the output name as an output already there', async () => {
    const [ws, , stderr, code] = await linked('ln -s dir t && gunzip t.gz')
    expect([stderr, code]).toEqual(['gzip: t already exists;\tnot overwritten\n', 2])
    await ws.close()
    const [forced, , , forcedCode] = await linked('ln -s dir t && gunzip -f t.gz')
    expect(forcedCode).toBe(0)
    expect(await out(forced, 'cd /data && ls -F && cat t')).toBe('dir/\nt\ntl.gz@\nhello\n')
    await forced.close()
  })

  it('needs a name typed with a slash to be a directory', async () => {
    const [ws, , stderr, code] = await linked('gunzip -c t.gz/')
    expect([stderr, code]).toEqual(['gzip: t.gz/: Not a directory\n', 1])
    await ws.close()
  })

  it('finds a link an earlier operand removed missing at its turn', async () => {
    const [ws, , stderr, code] = await linked('gunzip -f tl.gz tl.gz')
    expect([stderr, code]).toEqual(['gzip: tl.gz: No such file or directory\n', 1])
    expect(await out(ws, 'cd /data && ls')).toBe('dir\nt.gz\ntl\n')
    await ws.close()
  })
})
