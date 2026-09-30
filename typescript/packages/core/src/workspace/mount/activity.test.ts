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

import { setFlagsFromString } from 'node:v8'
import { runInNewContext } from 'node:vm'
import { expect, it } from 'vitest'
import { CachableAsyncIterator } from '../../io/cachable_iterator.ts'
import { VFSActivity } from './activity.ts'

it.each(['eof', 'error', 'close', 'bounded'])(
  'VFS usage ends with its stream (%s)',
  async (finish) => {
    const activity = new VFSActivity()
    async function* chunks(): AsyncGenerator<Uint8Array> {
      yield await Promise.resolve(new Uint8Array([1]))
      if (finish === 'error') throw new Error('read failed')
    }
    const source = activity.hold(
      finish === 'bounded' ? new CachableAsyncIterator(chunks()) : chunks(),
    )
    if (source instanceof Uint8Array) throw new Error('expected stream')
    let done = false
    const waiting = activity.wait().then(() => {
      done = true
    })
    await Promise.resolve()
    expect(done).toBe(false)
    const consume = async (): Promise<void> => {
      for await (const chunk of source) expect(chunk).toEqual(new Uint8Array([1]))
    }
    if (finish === 'close') {
      const iter = source[Symbol.asyncIterator]()
      await iter.return?.()
      await iter.return?.()
    } else if (source instanceof CachableAsyncIterator) {
      expect(await source.drainBounded(0)).toBeNull()
    } else if (finish === 'error') {
      await expect(consume()).rejects.toThrow('read failed')
    } else {
      await consume()
    }
    await waiting
    const release = activity.acquire()
    done = false
    const next = activity.wait().then(() => {
      done = true
    })
    await Promise.resolve()
    expect(done).toBe(false)
    release()
    await next
  },
)

it('exhausted cache streams do not keep a VFS active', async () => {
  async function* chunks(): AsyncGenerator<Uint8Array> {
    yield await Promise.resolve(new Uint8Array([1]))
  }
  const cached = new CachableAsyncIterator(chunks())
  await cached.drain()
  const activity = new VFSActivity()
  activity.hold(cached)
  await activity.wait()
})

it('close waits for a pending pull before releasing usage', async () => {
  const activity = new VFSActivity()
  let entered = (): void => undefined
  let resume = (): void => undefined
  const started = new Promise<void>((resolve) => {
    entered = resolve
  })
  const release = new Promise<void>((resolve) => {
    resume = resolve
  })
  async function* chunks(): AsyncGenerator<Uint8Array> {
    entered()
    await release
    yield new Uint8Array([1])
  }
  const source = activity.hold(chunks())
  if (source instanceof Uint8Array) throw new Error('expected stream')
  const iterator = source[Symbol.asyncIterator]()
  const pulling = iterator.next()
  await started
  let closed = false
  let idle = false
  const closing = iterator.return?.().then(() => {
    closed = true
  })
  const waiting = activity.wait().then(() => {
    idle = true
  })
  await Promise.resolve()
  expect(closed).toBe(false)
  expect(idle).toBe(false)
  resume()
  expect((await pulling).value).toEqual(new Uint8Array([1]))
  await Promise.all([closing, waiting])
})

function exposedGc(): (() => void) | undefined {
  const own = (globalThis as { gc?: () => void }).gc
  if (own !== undefined) return own
  // The flag is process-wide and stays on: resetting it could race another
  // worker's lookup, and a runtime that refuses it just skips the GC cases.
  try {
    setFlagsFromString('--expose-gc')
    const gc: unknown = runInNewContext('typeof gc === "function" ? gc : undefined')
    return typeof gc === 'function' ? (gc as () => void) : undefined
  } catch {
    return undefined
  }
}

const collect = exposedGc()

async function collectedWithin(settled: () => boolean, rounds = 50): Promise<boolean> {
  for (let i = 0; i < rounds && !settled(); i++) {
    collect?.()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  return settled()
}

it.skipIf(collect === undefined)(
  'a stream dropped unclosed releases its hold once collected (needs a gc the runtime exposes)',
  async () => {
    const activity = new VFSActivity()
    const pullOnceAndDrop = async (): Promise<void> => {
      async function* chunks(): AsyncGenerator<Uint8Array> {
        yield await Promise.resolve(new Uint8Array([1]))
        yield await Promise.resolve(new Uint8Array([2]))
      }
      const source = activity.hold(chunks())
      if (source instanceof Uint8Array) throw new Error('expected stream')
      const step = await source[Symbol.asyncIterator]().next()
      expect(step.value).toEqual(new Uint8Array([1]))
    }
    await pullOnceAndDrop()
    let idle = false
    void activity.wait().then(() => {
      idle = true
    })
    await Promise.resolve()
    expect(idle).toBe(false)
    expect(await collectedWithin(() => idle)).toBe(true)
  },
)

it.skipIf(collect === undefined)(
  'a stream whose source reaches back to it is still collected and released (needs a gc the runtime exposes)',
  async () => {
    const activity = new VFSActivity()
    let stream: WeakRef<object> | undefined
    const pullOnceAndDrop = async (): Promise<void> => {
      const owner: { held?: unknown } = {}
      async function* chunks(): AsyncGenerator<Uint8Array> {
        yield await Promise.resolve(new Uint8Array(owner.held === undefined ? [0] : [1]))
        yield await Promise.resolve(new Uint8Array([2]))
      }
      const source = activity.hold(chunks())
      if (source instanceof Uint8Array) throw new Error('expected stream')
      owner.held = source
      stream = new WeakRef(source)
      expect((await source[Symbol.asyncIterator]().next()).value).toEqual(new Uint8Array([1]))
    }
    await pullOnceAndDrop()
    let idle = false
    void activity.wait().then(() => {
      idle = true
    })
    expect(await collectedWithin(() => idle)).toBe(true)
    expect(stream?.deref()).toBeUndefined()
  },
)

it.skipIf(collect === undefined)(
  'a cache tee dropped unclosed releases its hold once collected (needs a gc the runtime exposes)',
  async () => {
    const activity = new VFSActivity()
    const pullOnceAndDrop = async (): Promise<void> => {
      async function* chunks(): AsyncGenerator<Uint8Array> {
        yield await Promise.resolve(new Uint8Array([1]))
        yield await Promise.resolve(new Uint8Array([2]))
      }
      const tee = activity.hold(new CachableAsyncIterator(chunks()))
      if (!(tee instanceof CachableAsyncIterator)) throw new Error('expected a tee')
      expect((await tee.next()).value).toEqual(new Uint8Array([1]))
    }
    await pullOnceAndDrop()
    let idle = false
    void activity.wait().then(() => {
      idle = true
    })
    expect(await collectedWithin(() => idle)).toBe(true)
  },
)

it.skipIf(collect === undefined)(
  'a stream closed explicitly is closed once, and a dropped one is released without a close (needs a gc the runtime exposes)',
  async () => {
    const activity = new VFSActivity()
    let explicitReturns = 0
    let droppedReturns = 0
    const counted = (onReturn: () => void): AsyncIterableIterator<Uint8Array> => ({
      next: () => Promise.resolve({ done: false, value: new Uint8Array([1]) }),
      return: () => {
        onReturn()
        return Promise.resolve({ done: true, value: undefined })
      },
      [Symbol.asyncIterator]() {
        return this
      },
    })
    const closeOneDropOne = async (): Promise<void> => {
      const closed = activity.hold(counted(() => explicitReturns++))
      const dropped = activity.hold(counted(() => droppedReturns++))
      if (closed instanceof Uint8Array || dropped instanceof Uint8Array) {
        throw new Error('expected streams')
      }
      await closed[Symbol.asyncIterator]().next()
      await closed[Symbol.asyncIterator]().return?.()
      await dropped[Symbol.asyncIterator]().next()
    }
    await closeOneDropOne()
    let idle = false
    void activity.wait().then(() => {
      idle = true
    })
    expect(await collectedWithin(() => idle)).toBe(true)
    expect([explicitReturns, droppedReturns]).toEqual([1, 0])
  },
)
