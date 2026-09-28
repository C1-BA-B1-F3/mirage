import { randomUUID } from 'node:crypto'
import { RedisAccessor } from '@struktoai/mirage-core/accessor/redis'
import { truncate } from '@struktoai/mirage-core/core/redis/truncate'
import { PathSpec } from '@struktoai/mirage-core/types'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RedisStore } from '../../vfs/redis/store.ts'

const url = process.env.REDIS_URL

describe.skipIf(url === undefined)('redis truncate', () => {
  let store: RedisStore
  let accessor: RedisAccessor
  const path = PathSpec.fromStrPath('/file')

  beforeEach(async () => {
    store = new RedisStore({ url: url ?? '', keyPrefix: `test:truncate:${randomUUID()}:` })
    await store.open()
    await store.setFile('/file', new TextEncoder().encode('hello'))
    accessor = new RedisAccessor(store)
  })

  afterEach(async () => {
    await store.clear()
    await store.close()
  })

  it('does not recreate a file deleted immediately before mutation', async () => {
    const mutate = store.truncateFile.bind(store)
    vi.spyOn(store, 'truncateFile').mockImplementation(async (p, length, modified, noCreate) => {
      await store.delFile(p)
      await store.delModified(p)
      return mutate(p, length, modified, noCreate)
    })
    await truncate(accessor, path, 2, true)
    expect(await store.getFile('/file')).toBeNull()
    expect(await store.getModified('/file')).toBeNull()
  })

  it.each([0, 2, 8])('atomically resizes to %i', async (length) => {
    await truncate(accessor, path, length, true)
    const expected = new Uint8Array(length)
    expected.set(new TextEncoder().encode('hello').subarray(0, length))
    expect(await store.getFile('/file')).toEqual(expected)
    expect(await store.getModified('/file')).not.toBeNull()
  })
})
