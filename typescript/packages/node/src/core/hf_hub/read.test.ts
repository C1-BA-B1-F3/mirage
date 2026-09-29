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

import { IndexEntry } from '@struktoai/mirage-core/cache/index/config'
import { RAMIndexCacheStore } from '@struktoai/mirage-core/cache/index/ram'
import { runWithRecording } from '@struktoai/mirage-core/observe/context'
import { PathSpec } from '@struktoai/mirage-core/types'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HfHubAccessor } from '../../accessor/hf_hub.ts'
import * as client from './client.ts'
import { read, rowToken } from './read.ts'
import { parseEntry } from './tree.ts'

function loaded(): HfHubAccessor {
  const accessor = new HfHubAccessor({ repoId: 'acme/widget' } as never)
  accessor.tree = new Map([
    ['m', parseEntry({ type: 'directory', oid: 'tree-m', size: 0, path: 'm' })],
    ['m/k.txt', parseEntry({ type: 'file', oid: 'oid-k', size: 5, path: 'm/k.txt' })],
  ])
  accessor.treeLoaded = true
  accessor.rowsCache = null
  return accessor
}

const PATH = new PathSpec({ virtual: '/m/m/k.txt', vfsPath: 'm/k.txt', directory: '/m/m/' })

afterEach(() => {
  vi.restoreAllMocks()
})

// A key named like its mount: neither `m/k.txt` nor `/m/k.txt` is virtual.
describe('hf_hub read record path', () => {
  it('records the virtual path', async () => {
    vi.spyOn(client, 'hubBytesTagged').mockResolvedValue([new TextEncoder().encode('hello'), ''])
    const [data, records] = await runWithRecording(() => read(loaded(), PATH))
    expect(new TextDecoder().decode(data)).toBe('hello')
    expect(records.map((r) => r.path)).toEqual(['/m/m/k.txt'])
  })
})

// One row whose four ids all differ, and none is a hash of the content, so
// every accepted ETag is distinguishable from every other and from a guess.
const ROW = new IndexEntry({
  id: 'O',
  name: 'f.bin',
  resourceType: 'file',
  extra: { oid: 'O', lfs_oid: 'L', xet_hash: 'X', last_commit: 'C' },
})
// The common case: a plain git file carries its oid and nothing else.
const PLAIN = new IndexEntry({ id: 'P', name: 'a.txt', resourceType: 'file', extra: { oid: 'P' } })
// A row that carries the LFS and Xet keys empty: a missing ETag must not match
// one of them.
const BLANK = new IndexEntry({
  id: 'P',
  name: 'a.txt',
  resourceType: 'file',
  extra: { oid: 'P', lfs_oid: '', xet_hash: '' },
})

describe('rowToken', () => {
  it.each([
    [ROW, '"O"', 'O'],
    [ROW, 'L', 'O'],
    [ROW, 'W/"X"', 'O'],
    [ROW, '"Z"', null],
    [ROW, '', null],
    [ROW, '"C"', null],
    [PLAIN, '"P"', 'P'],
    [PLAIN, '', null],
    [PLAIN, '"Z"', null],
    [BLANK, '', null],
  ])('stamps the oid only when the etag names the row (%#)', (entry, etag, expected) => {
    expect(rowToken(entry, etag)).toBe(expected)
  })

  it('never stamps an empty id', () => {
    // The ETag matches, so this takes the match branch; an empty id must
    // still come back as no token rather than ''.
    const entry = new IndexEntry({
      id: '',
      name: 'f',
      resourceType: 'file',
      extra: { lfs_oid: 'L' },
    })
    expect(rowToken(entry, '"L"')).toBeNull()
  })
})

describe('hf_hub read stamp', () => {
  it('stamps the oid when the etag names the row', async () => {
    vi.spyOn(client, 'hubBytesTagged').mockResolvedValue([
      new TextEncoder().encode('hello'),
      '"oid-k"',
    ])
    const [, records] = await runWithRecording(() => read(loaded(), PATH))
    expect(records.map((r) => r.fingerprint)).toEqual(['oid-k'])
  })

  it('stamps nothing when the bytes are another version', async () => {
    // The listing says oid-k, the download is a newer version: labelling
    // those bytes with the listing's oid is how a later revert would pass
    // them off as fresh.
    vi.spyOn(client, 'hubBytesTagged').mockResolvedValue([
      new TextEncoder().encode('newer'),
      '"another-version"',
    ])
    const [, records] = await runWithRecording(() => read(loaded(), PATH))
    expect(records.map((r) => r.fingerprint)).toEqual([null])
  })
})

describe('a read the Hub refuses', () => {
  it('is permission denied', async () => {
    vi.spyOn(client, 'hubGetResponse').mockRejectedValue(new client.HfHubError('nope', 403))
    const accessor = new HfHubAccessor({ repoId: 'acme/widget' } as never)
    const spec = new PathSpec({ virtual: '/a.txt', vfsPath: 'a.txt', directory: '/' })
    const err = await read(accessor, spec, new RAMIndexCacheStore()).catch((e: unknown) => e)
    expect((err as { code?: string }).code).toBe('EACCES')
    vi.restoreAllMocks()
  })
})

describe('a download the Hub refuses', () => {
  it.each([401, 403])('is permission denied for %i', async (status) => {
    // A gated repo lists its tree but refuses the file itself.
    vi.spyOn(client, 'hubBytesTagged').mockRejectedValue(new client.HfHubError('gated', status))
    const err = await read(loaded(), PATH).catch((e: unknown) => e)
    expect((err as { code?: string }).code).toBe('EACCES')
  })

  it('keeps a vanished file a hub error', async () => {
    // One file 404ing is not a refusal to show the repo.
    vi.spyOn(client, 'hubBytesTagged').mockRejectedValue(
      new client.HfHubError('gone', 404, 'EntryNotFound'),
    )
    const err = await read(loaded(), PATH).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(client.HfHubError)
  })
})
