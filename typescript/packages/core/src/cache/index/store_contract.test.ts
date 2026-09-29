import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IndexEntry, LookupStatus } from './config.ts'
import { RAMIndexCacheStore } from './ram.ts'
import { RedisIndexCacheStore } from './redis.ts'
import type { IndexCacheStore } from './store.ts'
import { IndexView } from './view.ts'
import { RAMFileCacheStore } from '../file/ram.ts'

const REDIS_URL = process.env.REDIS_URL

function entry(name = 'a'): IndexEntry {
  return new IndexEntry({
    id: name,
    name,
    resourceType: 'file',
    size: 2,
    remoteTime: '2026-09-05T10:55:39.123000Z',
    extra: { nested: { tags: ['x', 'y'] } },
  })
}

for (const backend of ['ram', 'redis']) {
  describe.skipIf(backend === 'redis' && REDIS_URL === undefined)(
    `${backend} index contract`,
    () => {
      let store: IndexCacheStore
      let keyPrefix: string
      beforeEach(() => {
        keyPrefix = `contract:[${crypto.randomUUID()}]:`
        store =
          backend === 'ram'
            ? new RAMIndexCacheStore({ ttl: 1 })
            : new RedisIndexCacheStore({
                ...(REDIS_URL === undefined ? {} : { url: REDIS_URL }),
                keyPrefix,
                ttl: 1,
              })
      })
      afterEach(async () => {
        await store.clear()
        await store.close()
      })

      it('reports the lifetime a listing gets when its writer names none', () => {
        expect(store.ttl).toBe(1)
      })

      it('lets a view report its store lifetime', async () => {
        const cache = new RAMFileCacheStore()
        try {
          expect(new IndexView(store, cache, '/', () => true).ttl).toBe(store.ttl)
        } finally {
          await cache.close()
        }
      })

      it('keeps missing, empty, fresh and expired listings distinct', async () => {
        expect((await store.listDir('/dir')).status).toBe(LookupStatus.NOT_FOUND)
        await store.setDir('/dir', [])
        expect((await store.listDir('/dir')).entries).toEqual([])
        await store.setDir('/dir', [
          ['b', entry('b')],
          ['a', entry()],
        ])
        expect((await store.listDir('/dir')).entries).toEqual(['/dir/b', '/dir/a'])
        const got = (await store.get('/dir/a')).entry
        expect(got).toEqual(entry().copyWith({ indexTime: got?.indexTime ?? '' }))
        expect(got?.indexTime).not.toBe('')
        await new Promise((resolve) => setTimeout(resolve, 1100))
        expect((await store.listDir('/dir')).status).toBe(LookupStatus.EXPIRED)
        expect((await store.get('/dir/a')).entry).toEqual(got)
        await store.invalidateDir('/dir')
        expect((await store.listDir('/dir')).status).toBe(LookupStatus.NOT_FOUND)
        expect((await store.get('/dir/a')).status).toBe(LookupStatus.NOT_FOUND)
      })

      it.each([-1000, 0])('does not clamp deadline offset %s', async (offset) => {
        await store.setDir('/dir', [['a', entry()]], new Date(Date.now() + offset))
        expect((await store.listDir('/dir')).status).toBe(LookupStatus.EXPIRED)
      })

      it('invalidates seeded listings without discarding metadata and can refill', async () => {
        const future = new Date(Date.now() + 3600000)
        store.seed(
          new Map([['/dir/a', entry()]]),
          new Map([
            ['/dir', ['/dir/a']],
            ['/empty', []],
          ]),
          future,
        )
        await store.invalidate()
        expect((await store.listDir('/dir')).status).toBe(LookupStatus.EXPIRED)
        expect((await store.listDir('/empty')).status).toBe(LookupStatus.EXPIRED)
        expect((await store.listDir('/absent')).status).toBe(LookupStatus.NOT_FOUND)
        expect((await store.get('/dir/a')).entry).toBeDefined()
        await store.setDir('/dir', [], future)
        expect((await store.listDir('/dir')).entries).toEqual([])
        expect((await store.listDir('/empty')).status).toBe(LookupStatus.EXPIRED)
      })

      it('merges seeds, copies input lists and persists them on close', async () => {
        const future = new Date(Date.now() + 3600000)
        const children = ['/one/a']
        store.seed(new Map([['/one/a', entry()]]), new Map([['/one', children]]), future)
        children.length = 0
        store.seed(
          new Map([['/two/b', entry('b')]]),
          new Map([
            ['/two', ['/two/b']],
            ['/empty', []],
          ]),
          future,
        )
        await store.close()
        await store.close()
        if (backend === 'redis') {
          store = new RedisIndexCacheStore({
            ...(REDIS_URL === undefined ? {} : { url: REDIS_URL }),
            keyPrefix,
          })
        }
        expect((await store.listDir('/one')).entries).toEqual(['/one/a'])
        expect((await store.listDir('/two')).entries).toEqual(['/two/b'])
        expect((await store.listDir('/empty')).entries).toEqual([])
        expect([...(await store.entries())].map(([path]) => path).sort()).toEqual([
          '/one/a',
          '/two/b',
        ])
      })

      it('makes invalidation visible to other clients', async () => {
        const peer =
          backend === 'ram'
            ? store
            : new RedisIndexCacheStore({
                ...(REDIS_URL === undefined ? {} : { url: REDIS_URL }),
                keyPrefix,
              })
        try {
          const future = new Date(Date.now() + 3600000)
          await store.setDir('/dir', [['a', entry()]], future)
          await peer.invalidate()
          expect((await store.listDir('/dir')).status).toBe(LookupStatus.EXPIRED)
          await store.setDir('/dir', [], future)
          expect((await peer.listDir('/dir')).entries).toEqual([])
          await peer.invalidateDir('/dir')
          await store.invalidate()
          expect((await peer.listDir('/dir')).status).toBe(LookupStatus.NOT_FOUND)
        } finally {
          if (peer !== store) await peer.close()
        }
      })

      it('discards pending seeds on clear', async () => {
        store.seed(new Map([['/a', entry()]]), new Map([['/', ['/a']]]), new Date())
        await store.clear()
        expect(await store.entries()).toEqual(new Map())
        expect((await store.listDir('/')).status).toBe(LookupStatus.NOT_FOUND)
      })

      it('invalidates literal prefixes with path boundaries', async () => {
        const future = new Date(Date.now() + 3600000)
        for (const path of ['/a[1]', '/a[1]/nested', '/a1', '/a[1]-other']) {
          await store.setDir(path, [['a', entry()]], future)
        }
        await store.invalidatePrefix('/a[1]')
        for (const path of ['/a[1]', '/a[1]/nested']) {
          expect((await store.listDir(path)).status).toBe(LookupStatus.NOT_FOUND)
          expect((await store.get(path + '/a')).status).toBe(LookupStatus.NOT_FOUND)
        }
        for (const path of ['/a1', '/a[1]-other']) {
          expect((await store.listDir(path)).entries).toEqual([path + '/a'])
        }
      })
    },
  )
}
