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

import { mountKey } from '../utils/key_prefix.ts'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FileStat, FileType, PathSpec } from '../types.ts'
import { withCacheMutation } from './file/io.ts'
import { RAMFileCacheStore } from './file/ram.ts'
import { IndexEntry } from './index/config.ts'
import { LISTING_TRUST_WINDOW } from './index/constants.ts'
import { RAMIndexCacheStore } from './index/ram.ts'
import { runInCommandScope } from './index/scope.ts'
import { IndexView } from './index/view.ts'
import { CacheManager } from './manager.ts'
import { enoent } from '../utils/errors.ts'

async function seeded(): Promise<[RAMFileCacheStore, RAMIndexCacheStore]> {
  const cache = new RAMFileCacheStore()
  const index = new RAMIndexCacheStore({ ttl: 600 })
  await cache.set('/data/arch/h.txt', new TextEncoder().encode('two\n'))
  await index.setDir('/data/arch', [
    ['h.txt', new IndexEntry({ id: 'h', name: 'h.txt', resourceType: 'file' })],
  ])
  return [cache, index]
}

describe('CacheManager', () => {
  it('write evicts file entry and parent listing', async () => {
    const [cache, index] = await seeded()
    const manager = new CacheManager(cache, index, '/data/', true)
    await manager.invalidateAfterWrite('/arch/h.txt')
    expect(await cache.exists('/data/arch/h.txt')).toBe(false)
    const listing = await index.listDir('/data/arch')
    expect(listing.entries ?? null).toBeNull()
  })

  it('unlink evicts file entry, listing, and index entry', async () => {
    const [cache, index] = await seeded()
    const manager = new CacheManager(cache, index, '/data/', true)
    await manager.invalidateAfterUnlink('/arch/h.txt')
    expect(await cache.exists('/data/arch/h.txt')).toBe(false)
    const listing = await index.listDir('/data/arch')
    expect(listing.entries ?? null).toBeNull()
    const entry = await index.get('/data/arch/h.txt')
    expect(entry.entry ?? null).toBeNull()
  })

  it('local mount keeps file cache but invalidates index', async () => {
    const [cache, index] = await seeded()
    const manager = new CacheManager(cache, index, '/data/', false)
    await manager.invalidateAfterWrite('/arch/h.txt')
    expect(await cache.exists('/data/arch/h.txt')).toBe(true)
    const listing = await index.listDir('/data/arch')
    expect(listing.entries ?? null).toBeNull()
  })

  it('accepts PathSpec input and maps to the virtual key', async () => {
    const [cache, index] = await seeded()
    const manager = new CacheManager(cache, index, '/data/', true)
    const spec = new PathSpec({
      virtual: '/data/arch/h.txt',
      directory: '/data/arch',
      vfsPath: mountKey('/data/arch/h.txt', '/data'),
    })
    await manager.invalidateAfterWrite(spec)
    expect(await cache.exists('/data/arch/h.txt')).toBe(false)
  })

  it('tolerates a missing index', async () => {
    const cache = new RAMFileCacheStore()
    await cache.set('/data/a.txt', new TextEncoder().encode('x'))
    const manager = new CacheManager(cache, null, '/data/', true)
    await manager.invalidateAfterWrite('/a.txt')
    expect(await cache.exists('/data/a.txt')).toBe(false)
  })

  it('invalidateAncestors walks up to the mount root', async () => {
    // One put materializes every missing level of the key, so every listing
    // above the written file gained an entry.
    const index = new RAMIndexCacheStore({ ttl: 600 })
    for (const dir of ['/data', '/data/a', '/data/a/b']) await index.setDir(dir, [])
    const manager = new CacheManager(null, index, '/data/', true)
    await manager.invalidateAncestors(PathSpec.fromStrPath('/a/b/c.txt'))
    expect((await index.listDir('/data')).entries ?? null).toBeNull()
    expect((await index.listDir('/data/a')).entries ?? null).toBeNull()
    // The immediate parent is invalidateAfterWrite's job, not this one.
    expect((await index.listDir('/data/a/b')).entries ?? null).not.toBeNull()
  })

  it('invalidateAncestors reaches the root listing', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    for (const dir of ['/', '/a']) await index.setDir(dir, [])
    const manager = new CacheManager(null, index, '/', true)
    await manager.invalidateAncestors(PathSpec.fromStrPath('/a/b/c.txt'))
    expect((await index.listDir('/')).entries ?? null).toBeNull()
    expect((await index.listDir('/a')).entries ?? null).toBeNull()
  })

  it("drops this mount's bodies without touching a neighbour", async () => {
    const [cache, index] = await seeded()
    await cache.set('/other/keep.txt', new TextEncoder().encode('safe'))
    const manager = new CacheManager(cache, index, '/data/', true)
    await manager.dropPrefix()
    expect(await cache.exists('/data/arch/h.txt')).toBe(false)
    expect(await cache.exists('/other/keep.txt')).toBe(true)
  })

  it('leaves a non-caching mount alone', async () => {
    const [cache, index] = await seeded()
    const manager = new CacheManager(cache, index, '/data/', false)
    await manager.dropPrefix()
    expect(await cache.exists('/data/arch/h.txt')).toBe(true)
  })

  it('invalidateSubtree drops nested bodies and listings', async () => {
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const entry = new IndexEntry({ id: '1', name: 'f', resourceType: 'file' })
    await cache.set('/data/chan/day/chat.jsonl', new TextEncoder().encode('one\n'))
    await cache.set('/data/chan/day/files/a.png', new TextEncoder().encode('png'))
    await index.setDir('/data/chan/day', [['chat.jsonl', entry]])
    await index.setDir('/data/chan/day/files', [['a.png', entry]])
    await index.setDir('/data/chan', [['day', entry]])
    const manager = new CacheManager(cache, index, '/data/', true)
    await manager.invalidateSubtree(PathSpec.fromStrPath('/chan/day'))
    expect(await cache.exists('/data/chan/day/files/a.png')).toBe(false)
    expect((await index.listDir('/data/chan/day')).entries).toBeUndefined()
    expect((await index.listDir('/data/chan/day/files')).entries).toBeUndefined()
    expect((await index.listDir('/data/chan')).entries).toBeUndefined()
  })

  it('a write does not reach into the subtree', async () => {
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const entry = new IndexEntry({ id: '1', name: 'f', resourceType: 'file' })
    await index.setDir('/data/chan/day/files', [['a.png', entry]])
    const manager = new CacheManager(cache, index, '/data/', true)
    await manager.invalidateAfterWrite(PathSpec.fromStrPath('/chan/day'))
    expect((await index.listDir('/data/chan/day/files')).entries).toEqual([
      '/data/chan/day/files/a.png',
    ])
  })

  it('a relative path that looks prefixed is still prefixed', async () => {
    // '/day' starts with the '/d' prefix as characters while naming something
    // else; reading it as absolute evicted '/day' and left '/d/day' cached,
    // which is an eviction that hits no key.
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const entry = new IndexEntry({ id: '1', name: 'f', resourceType: 'file' })
    await index.setDir('/d/day', [['chat.jsonl', entry]])
    const manager = new CacheManager(cache, index, '/d/', true)
    await manager.invalidateAfterUnlink(PathSpec.fromStrPath('/day'))
    expect((await index.listDir('/d/day')).entries).toBeUndefined()
  })

  it('reaches every key on a root mount', async () => {
    // A root mount strips to the empty prefix, so the eviction argument is '/'
    // and matches every key rather than nothing.
    const cache = new RAMFileCacheStore()
    await cache.set('/a.txt', new TextEncoder().encode('x'))
    await cache.set('/sub/b.txt', new TextEncoder().encode('y'))
    const manager = new CacheManager(cache, null, '/', true)
    await manager.dropPrefix()
    expect(await cache.exists('/a.txt')).toBe(false)
    expect(await cache.exists('/sub/b.txt')).toBe(false)
  })
})

describe('CacheManager read gate', () => {
  const spec = (path = '/data/x.txt') =>
    new PathSpec({
      vfsPath: mountKey(path, '/data/'),
      virtual: path,
      directory: '/data/',
    })

  async function withEntry(data = new TextEncoder().encode('cached')) {
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    await cache.set('/data/x.txt', data)
    return [cache, index] as const
  }

  const ownsAll = () => true

  it('a refusal withholds the cached bytes', async () => {
    const [cache, index] = await withEntry()
    const asked: string[] = []
    const manager = new CacheManager(cache, index, '/data/', true, ownsAll, (key) => {
      asked.push(key)
      return Promise.resolve(false)
    })
    expect(await manager.cachedBytes(spec())).toBeNull()
    expect(asked).toEqual(['/data/x.txt'])
  })

  it('is not asked for a path the cache does not hold', async () => {
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const asked: string[] = []
    const manager = new CacheManager(cache, index, '/data/', true, ownsAll, (key) => {
      asked.push(key)
      return Promise.resolve(true)
    })
    expect(await manager.cachedBytes(spec())).toBeNull()
    expect(asked).toEqual([])
  })

  it('is not asked for a non-caching mount', async () => {
    const [cache, index] = await withEntry()
    const asked: string[] = []
    const manager = new CacheManager(cache, index, '/data/', false, ownsAll, (key) => {
      asked.push(key)
      return Promise.resolve(true)
    })
    expect(await manager.cachedBytes(spec())).toBeNull()
    expect(asked).toEqual([])
  })

  it('is not asked for a key the mount no longer owns', async () => {
    const [cache, index] = await withEntry()
    const asked: string[] = []
    const manager = new CacheManager(
      cache,
      index,
      '/data/',
      true,
      () => false,
      (key) => {
        asked.push(key)
        return Promise.resolve(true)
      },
    )
    expect(await manager.cachedBytes(spec())).toBeNull()
    expect(asked).toEqual([])
  })

  it('a gate reporting the object gone propagates', async () => {
    const [cache, index] = await withEntry()
    const manager = new CacheManager(cache, index, '/data/', true, ownsAll, () =>
      Promise.reject(enoent('/data/x.txt')),
    )
    await expect(manager.cachedBytes(spec())).rejects.toThrow()
  })

  it('cachedSize reports the length without revalidating', async () => {
    const [cache, index] = await withEntry()
    const asked: string[] = []
    const manager = new CacheManager(cache, index, '/data/', true, ownsAll, (key) => {
      asked.push(key)
      return Promise.resolve(false)
    })
    expect(await manager.cachedSize(spec())).toBe(6)
    expect(asked).toEqual([])
  })

  it('cachedSize of an empty render is 0, not null', async () => {
    const [cache, index] = await withEntry(new Uint8Array(0))
    const manager = new CacheManager(cache, index, '/data/', true)
    expect(await manager.cachedSize(spec())).toBe(0)
  })

  it('cachedSize of an absent path is null', async () => {
    const cache = new RAMFileCacheStore()
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(cache, index, '/data/', true)
    expect(await manager.cachedSize(spec())).toBeNull()
  })
})

function settleWithin(work: Promise<unknown>, ms: number): Promise<'done' | 'pending'> {
  return Promise.race([
    work.then(() => 'done' as const),
    new Promise<'pending'>((resolve) => {
      setTimeout(() => {
        resolve('pending')
      }, ms)
    }),
  ])
}

describe('CacheManager index views', () => {
  it('shares one view per store', () => {
    const manager = new CacheManager(new RAMFileCacheStore(), null, '/data', true)
    const a = new RAMIndexCacheStore()
    expect(manager.scopeIndex(a)).toBe(manager.scopeIndex(a))
  })

  it('builds a new view when the store is replaced', async () => {
    const manager = new CacheManager(new RAMFileCacheStore(), null, '/data', true)
    const a = new RAMIndexCacheStore()
    const b = new RAMIndexCacheStore()
    manager.scopeIndex(a)
    const view = manager.scopeIndex(b)
    expect((view as IndexView).store).toBe(b)
    await view.setDir('/data', [
      ['x', new IndexEntry({ id: 'x', name: 'x', resourceType: 'file' })],
    ])
    expect((await b.listDir('/data')).entries).toEqual(['/data/x'])
    expect((await a.listDir('/data')).entries).toBeUndefined()
  })

  it('hands back a view it is given, whatever it has memoized', () => {
    const cache = new RAMFileCacheStore()
    const manager = new CacheManager(cache, null, '/data', true)
    manager.scopeIndex(new RAMIndexCacheStore())
    const other = new IndexView(new RAMIndexCacheStore(), cache, '/data', () => true)
    expect(manager.scopeIndex(other)).toBe(other)
  })

  it('hands back the raw store without a file cache', () => {
    const a = new RAMIndexCacheStore()
    const manager = new CacheManager(null, null, '/data', true)
    expect(manager.scopeIndex(a)).toBe(a)
  })

  it('refuses to build a lock-held view over a view', () => {
    const cache = new RAMFileCacheStore()
    const manager = new CacheManager(cache, null, '/data', true)
    const view = new IndexView(new RAMIndexCacheStore(), cache, '/data', () => true)
    expect(typeof manager.scopeIndexLocked).toBe('function')
    expect(() => manager.scopeIndexLocked(view)).toThrow()
  })

  it('hands back the raw store for a lock-held scope without a file cache', () => {
    const a = new RAMIndexCacheStore()
    const manager = new CacheManager(null, null, '/data', true)
    expect(manager.scopeIndexLocked(a)).toBe(a)
  })

  it('never memoizes a lock-held view or shares the memo slot', async () => {
    const cache = new RAMFileCacheStore()
    const manager = new CacheManager(cache, null, '/data', true)
    const a = new RAMIndexCacheStore()
    const locked = manager.scopeIndexLocked(a)
    expect(locked).toBeInstanceOf(IndexView)
    expect(manager.scopeIndexLocked(a)).not.toBe(locked)
    const shared = manager.scopeIndex(a)
    expect(shared).not.toBe(locked)
    let release = (): void => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const held = withCacheMutation(cache, () => gate)
    try {
      const pending = shared.get('/data/x')
      expect(await settleWithin(pending, 20)).toBe('pending')
      release()
      expect(await settleWithin(pending, 1000)).toBe('done')
    } finally {
      release()
      await held
    }
  })
})

describe('what a mount has listed since a command started', () => {
  // A glob writes through its own locked view; the command's later ls
  // through the shared view must trust that same write.
  it('counts a write through the locked view for the shared one', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await runInCommandScope(async () => {
      await manager.scopeIndexLocked(index).setDir('/data', [])
      expect(manager.listingTrusted('/data')).toBe(true)
      expect(manager.listingTrusted('/data/other')).toBe(false)
    })
  })

  it('does not count a write before the command', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await manager.scopeIndex(index).setDir('/data', [])
    await runInCommandScope(() => {
      expect(manager.listingTrusted('/data')).toBe(false)
      return Promise.resolve()
    })
  })

  it('forgets what the old store was written when the store is replaced', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await runInCommandScope(async () => {
      await manager.scopeIndex(index).setDir('/data', [])
      manager.scopeIndex(new RAMIndexCacheStore({ ttl: 600 }))
      expect(manager.listingTrusted('/data')).toBe(false)
    })
  })
})

describe('which listings a mount trusts', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('trusts a listing for the window outside any command', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await manager.scopeIndex(index).setDir('/data', [])
    vi.setSystemTime(Date.now() + LISTING_TRUST_WINDOW * 1000 - 10)
    expect(manager.listingTrusted('/data')).toBe(true)
    expect(manager.listingTrusted('/data/other')).toBe(false)
    vi.setSystemTime(Date.now() + 20)
    expect(manager.listingTrusted('/data')).toBe(false)
  })

  // Date.now can step backwards; elapsed time below zero is no evidence the
  // listing is recent.
  it('does not extend the window when the clock ran backwards', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await manager.scopeIndex(index).setDir('/data', [])
    vi.setSystemTime(Date.now() - 5000)
    expect(manager.listingTrusted('/data')).toBe(false)
  })

  // A listing the previous command wrote a moment ago is still re-listed by
  // the next one: the window is only for reads that belong to no command.
  it('does not apply the window inside a command', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await manager.scopeIndex(index).setDir('/data', [])
    vi.setSystemTime(Date.now() + 10)
    await runInCommandScope(async () => {
      expect(manager.listingTrusted('/data')).toBe(false)
      await manager.scopeIndex(index).setDir('/data', [])
      vi.setSystemTime(Date.now() + LISTING_TRUST_WINDOW * 10_000)
      expect(manager.listingTrusted('/data')).toBe(true)
    })
  })
})

describe('what a probe saw this command', () => {
  const path = PathSpec.fromStrPath('/data/arch/h.txt')
  const probed = (): FileStat => new FileStat({ name: 'h.txt', size: 4, type: FileType.FILE })

  it('is served for the rest of its command only', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    const stat = probed()
    await runInCommandScope(() => {
      manager.noteProbed(path, stat)
      expect(manager.probedStat(path)).toBe(stat)
      expect(manager.probedStat(PathSpec.fromStrPath('/data/arch/other'))).toBeNull()
      return Promise.resolve()
    })
    expect(manager.probedStat(path)).toBeNull()
    await runInCommandScope(() => {
      expect(manager.probedStat(path)).toBeNull()
      return Promise.resolve()
    })
  })

  it('is never served for a probe outside a command', () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    manager.noteProbed(path, probed())
    expect(manager.probedStat(path)).toBeNull()
  })

  // Any write the command makes, to any path, retires what its probes saw:
  // coarser than per path, never a stale answer.
  for (const invalidate of [
    'invalidateAfterWrite',
    'invalidateAfterUnlink',
    'invalidateSubtree',
  ] as const) {
    it(`is dropped by ${invalidate} in the same command`, async () => {
      const index = new RAMIndexCacheStore({ ttl: 600 })
      const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
      await runInCommandScope(async () => {
        manager.noteProbed(path, probed())
        await manager[invalidate](PathSpec.fromStrPath('/data/elsewhere'))
        expect(manager.probedStat(path)).toBeNull()
      })
    })
  }

  it('is forgotten when a later probe found nothing', async () => {
    const index = new RAMIndexCacheStore({ ttl: 600 })
    const manager = new CacheManager(new RAMFileCacheStore(), index, '/data/', true)
    await runInCommandScope(() => {
      manager.noteProbed(path, probed())
      manager.noteProbed(path, null)
      expect(manager.probedStat(path)).toBeNull()
      return Promise.resolve()
    })
  })
})
