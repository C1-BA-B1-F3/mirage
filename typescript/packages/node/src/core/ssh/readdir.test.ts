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
import type { FileEntryWithStats } from 'ssh2'
import { RAMIndexCacheStore } from '@struktoai/mirage-core/cache/index/ram'
import { PathSpec } from '@struktoai/mirage-core/types'
import { mountKey } from '@struktoai/mirage-core/utils/key_prefix'
import { type FakeSftp, makeFakeAccessor } from './_test_utils.ts'
import { readdir } from './readdir.ts'

function spec(p: string): PathSpec {
  return PathSpec.fromStrPath(p)
}

describe('core/ssh/readdir', () => {
  it('returns sorted virtual paths under a directory', async () => {
    const accessor = makeFakeAccessor({
      files: new Map([
        ['/data/b.txt', { data: new Uint8Array() }],
        ['/data/a.txt', { data: new Uint8Array() }],
      ]),
      dirs: new Map([
        ['/', {}],
        ['/data', {}],
      ]),
    })
    const out = await readdir(accessor, spec('/data'))
    expect(out).toEqual(['/data/a.txt', '/data/b.txt'])
  })

  it('throws ENOENT for a missing directory', async () => {
    const accessor = makeFakeAccessor({
      files: new Map(),
      dirs: new Map([['/', {}]]),
    })
    await expect(readdir(accessor, spec('/missing'))).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('throws ENOTDIR for an operand under a file', async () => {
    // SFTP 3 answers `/a.txt/x` with NO_SUCH_FILE exactly as it does a name
    // that is simply absent, so only the ancestor walk can tell GNU's "Not a
    // directory" from "No such file or directory".
    const accessor = makeFakeAccessor({
      files: new Map([['/a.txt', { data: new Uint8Array() }]]),
      dirs: new Map([['/', {}]]),
    })
    await expect(readdir(accessor, spec('/a.txt/x'))).rejects.toMatchObject({
      code: 'ENOTDIR',
    })
    await expect(readdir(accessor, spec('/nope/deeper'))).rejects.toMatchObject({
      code: 'ENOENT',
    })
  })

  it('preserves the mount prefix in returned paths', async () => {
    const accessor = makeFakeAccessor({
      files: new Map([['/data/a.txt', { data: new Uint8Array() }]]),
      dirs: new Map([
        ['/', {}],
        ['/data', {}],
      ]),
    })
    const p = new PathSpec({
      virtual: '/mnt/ssh/data',
      directory: '/mnt/ssh/data',
      vfsPath: mountKey('/mnt/ssh/data', '/mnt/ssh'),
    })
    const out = await readdir(accessor, p)
    expect(out).toEqual(['/mnt/ssh/data/a.txt'])
  })
})

function dataState(): FakeSftp {
  return {
    files: new Map([['/data/a.txt', { data: new TextEncoder().encode('hello') }]]),
    dirs: new Map([
      ['/', {}],
      ['/data', {}],
      ['/data/docs', { mtime: 1700000000 }],
    ]),
  }
}

describe('core/ssh/readdir listing cache', () => {
  it('stores sftp attrs in the index', async () => {
    const index = new RAMIndexCacheStore()
    const accessor = makeFakeAccessor(dataState())
    expect(await readdir(accessor, spec('/data'), index)).toEqual(['/data/a.txt', '/data/docs'])
    expect((await index.listDir('/data')).entries).toEqual(['/data/a.txt', '/data/docs'])
    const file = (await index.get('/data/a.txt')).entry
    expect(file?.resourceType).toBe('file')
    expect(file?.size).toBe(5)
    const folder = (await index.get('/data/docs')).entry
    expect(folder?.resourceType).toBe('folder')
    expect(folder?.size).toBeNull()
    expect(folder?.remoteTime).toBe('2023-11-14T22:13:20Z')
  })

  it('answers a cached listing without asking the server', async () => {
    const index = new RAMIndexCacheStore()
    const state = dataState()
    const accessor = makeFakeAccessor(state)
    await readdir(accessor, spec('/data'), index)
    state.files.set('/data/b.txt', { data: new Uint8Array() })
    expect(await readdir(accessor, spec('/data'), index)).toEqual(['/data/a.txt', '/data/docs'])
  })

  it('lists the server again once the listing is dropped', async () => {
    const index = new RAMIndexCacheStore()
    const state = dataState()
    const accessor = makeFakeAccessor(state)
    await readdir(accessor, spec('/data'), index)
    state.files.set('/data/b.txt', { data: new Uint8Array() })
    await index.invalidateDir('/data')
    expect(await readdir(accessor, spec('/data'), index)).toEqual([
      '/data/a.txt',
      '/data/b.txt',
      '/data/docs',
    ])
  })

  // An SFTP server may leave the time fields out of a readdir entry; ssh2
  // then carries no mtime, and the listing still stores the entry.
  it('stores an entry whose attrs carry no mtime', async () => {
    const index = new RAMIndexCacheStore()
    const accessor = makeFakeAccessor({ files: new Map(), dirs: new Map([['/', {}]]) })
    const sftp = await accessor.sftp()
    const entry = { filename: 'x.txt', longname: '', attrs: { mode: 0o100644, size: 1 } }
    sftp.readdir = ((_path: string, cb: (err: undefined, list: FileEntryWithStats[]) => void) => {
      cb(undefined, [entry as unknown as FileEntryWithStats])
    }) as typeof sftp.readdir
    expect(await readdir(accessor, spec('/'), index)).toEqual(['/x.txt'])
    const row = (await index.get('/x.txt')).entry
    expect(row?.size).toBe(1)
    expect(row?.remoteTime).toBe('')
  })

  it('keys the listing by the mount-prefixed path', async () => {
    const index = new RAMIndexCacheStore()
    const accessor = makeFakeAccessor(dataState())
    const p = new PathSpec({
      virtual: '/mnt/ssh/data',
      directory: '/mnt/ssh/data',
      vfsPath: mountKey('/mnt/ssh/data', '/mnt/ssh'),
    })
    await readdir(accessor, p, index)
    expect((await index.listDir('/mnt/ssh/data')).entries).toEqual([
      '/mnt/ssh/data/a.txt',
      '/mnt/ssh/data/docs',
    ])
  })
})
