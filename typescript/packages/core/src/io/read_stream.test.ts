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
import { describe, expect, it, vi } from 'vitest'
import { applyOpLimit } from '../commands/builtin/utils/limit.ts'
import { Limit } from '../types.ts'
import { capEnd, ReadStream } from './read_stream.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

class SpySource implements AsyncIterator<Uint8Array> {
  pulls = 0
  closed = false
  private readonly chunks: Uint8Array[]

  constructor(
    chunks: readonly Uint8Array[],
    private readonly failAt: number | null = null,
  ) {
    this.chunks = [...chunks]
  }

  async next(): Promise<IteratorResult<Uint8Array>> {
    await Promise.resolve()
    this.pulls++
    if (this.failAt !== null && this.pulls === this.failAt) throw new Error('backend went away')
    const chunk = this.chunks.shift()
    if (chunk === undefined) return { done: true, value: undefined }
    return { done: false, value: chunk }
  }

  return(): Promise<IteratorResult<Uint8Array>> {
    this.closed = true
    return Promise.resolve({ done: true, value: undefined })
  }
}

function split(data: Uint8Array, size: number): Uint8Array[] {
  const out: Uint8Array[] = []
  for (let at = 0; at < data.byteLength; at += size) out.push(data.subarray(at, at + size))
  return out
}

async function opened(source: SpySource): Promise<ReadStream> {
  const step = await source.next()
  return step.done === true ? new ReadStream(null, null) : new ReadStream(step.value, source)
}

async function collect(stream: AsyncIterable<Uint8Array>): Promise<Uint8Array[]> {
  const out: Uint8Array[] = []
  for await (const chunk of stream) out.push(chunk)
  return out
}

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

const collectGarbage = exposedGc()

async function collectedWithin(settled: () => boolean, rounds = 50): Promise<boolean> {
  for (let i = 0; i < rounds && !settled(); i++) {
    collectGarbage?.()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  return settled()
}

function join(chunks: readonly Uint8Array[]): Uint8Array {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.byteLength, 0))
  let at = 0
  for (const chunk of chunks) {
    out.set(chunk, at)
    at += chunk.byteLength
  }
  return out
}

describe('capEnd', () => {
  it('keeps bytes up to maxBytes', () => {
    const chunk = ENC.encode('abcdef')
    expect(capEnd(chunk, new Limit({ maxBytes: 4 }), 0, 0)).toBe(4)
    expect(capEnd(chunk, new Limit({ maxBytes: 4 }), 2, 0)).toBe(2)
    expect(capEnd(chunk, new Limit({ maxBytes: 10 }), 0, 0)).toBe(6)
  })

  it('keeps through the Nth newline for maxLines', () => {
    const chunk = ENC.encode('a\nb\nc\n')
    expect(capEnd(chunk, new Limit({ maxLines: 2 }), 0, 0)).toBe(4)
    expect(capEnd(chunk, new Limit({ maxLines: 2 }), 0, 1)).toBe(2)
    expect(capEnd(ENC.encode('abc'), new Limit({ maxLines: 1 }), 0, 0)).toBe(3)
  })

  it('takes the tighter of both caps', () => {
    const chunk = ENC.encode('a\nb\nc\n')
    expect(capEnd(chunk, new Limit({ maxLines: 2, maxBytes: 3 }), 0, 0)).toBe(3)
    expect(capEnd(chunk, new Limit({ maxLines: 2, maxBytes: 5 }), 0, 0)).toBe(4)
  })

  it('keeps nothing once the cap is spent', () => {
    const chunk = ENC.encode('a\nb\n')
    expect(capEnd(chunk, new Limit({ maxBytes: 4 }), 4, 0)).toBe(0)
    expect(capEnd(chunk, new Limit({ maxLines: 2 }), 0, 2)).toBe(0)
    expect(capEnd(chunk, new Limit({ maxBytes: 0 }), 0, 0)).toBe(0)
  })
})

describe('ReadStream', () => {
  it.each([1, 2, 3, 7, 64])(
    'cuts a stream split into chunks of %i where a whole-bytes cap cuts it',
    async (size) => {
      const data = ENC.encode('one\ntwo\nthree\nfour\nfive\nsix\n')
      for (const limit of [
        new Limit({ maxBytes: 5 }),
        new Limit({ maxLines: 2 }),
        new Limit({ maxLines: 3, maxBytes: 11 }),
        new Limit({ maxLines: 4, maxBytes: 100 }),
        new Limit({ maxBytes: 0 }),
        new Limit({ maxLines: 0 }),
        new Limit({ maxBytes: 1000 }),
      ]) {
        const stream = await opened(new SpySource(split(data, size)))
        stream.cap(limit)
        const whole = (await applyOpLimit(data, limit)) as Uint8Array
        expect(DEC.decode(join(await collect(stream)))).toBe(DEC.decode(whole))
      }
    },
  )

  it('yields the first chunk then the source and settles once with the total at EOF', async () => {
    const source = new SpySource([ENC.encode('a'), ENC.encode('bc'), ENC.encode('de')])
    const stream = await opened(source)
    const settled: number[] = []
    void stream.onSettle((moved) => settled.push(moved))
    const iterator = stream[Symbol.asyncIterator]()
    expect(DEC.decode((await iterator.next()).value as Uint8Array)).toBe('a')
    expect(DEC.decode((await iterator.next()).value as Uint8Array)).toBe('bc')
    expect(DEC.decode((await iterator.next()).value as Uint8Array)).toBe('de')
    expect(settled).toEqual([])
    expect((await iterator.next()).done).toBe(true)
    expect(settled).toEqual([5])
    expect((await iterator.next()).done).toBe(true)
    await stream.return()
    expect(settled).toEqual([5])
    const late: number[] = []
    void stream.onSettle((moved) => late.push(moved))
    expect(late).toEqual([5])
  })

  it('closes the source on return before EOF and settles with the partial count', async () => {
    const source = new SpySource([ENC.encode('ab'), ENC.encode('cd'), ENC.encode('ef')])
    const stream = await opened(source)
    const settled: number[] = []
    void stream.onSettle((moved) => settled.push(moved))
    const iterator = stream[Symbol.asyncIterator]()
    await iterator.next()
    await iterator.next()
    expect(source.pulls).toBe(2)
    await stream.return()
    expect(source.closed).toBe(true)
    expect(settled).toEqual([4])
    expect((await iterator.next()).done).toBe(true)
    expect(source.pulls).toBe(2)
    expect(settled).toEqual([4])
  })

  it('settles on a failed pull and propagates the error', async () => {
    const source = new SpySource([ENC.encode('ab'), ENC.encode('cd')], 2)
    const stream = await opened(source)
    const settled: number[] = []
    void stream.onSettle((moved) => settled.push(moved))
    const iterator = stream[Symbol.asyncIterator]()
    await iterator.next()
    await expect(iterator.next()).rejects.toThrow('backend went away')
    expect(settled).toEqual([2])
    expect((await iterator.next()).done).toBe(true)
  })

  it('stops pulling the source once a truncating cap is reached', async () => {
    const chunks = Array.from({ length: 10 }, (_, i) => ENC.encode(String(i).repeat(4)))
    const source = new SpySource(chunks)
    const stream = await opened(source)
    stream.cap(new Limit({ maxBytes: 6 }))
    const settled: number[] = []
    void stream.onSettle((moved) => settled.push(moved))
    expect(DEC.decode(join(await collect(stream)))).toBe('000011')
    expect(source.pulls).toBe(2)
    expect(source.closed).toBe(true)
    expect(settled).toEqual([8])
  })

  it('whole is one chunk and already settled', async () => {
    const stream = ReadStream.whole(ENC.encode('hello'))
    const settled: number[] = []
    void stream.onSettle((moved) => settled.push(moved))
    expect(settled).toEqual([5])
    const chunks = await collect(stream)
    expect(chunks.map((c) => DEC.decode(c))).toEqual(['hello'])
    expect(settled).toEqual([5])
  })

  it('surfaces a settle callback that rejects from the pull or return that settled it', async () => {
    const atEof = await opened(new SpySource([ENC.encode('ab')]))
    void atEof.onSettle(() => Promise.reject(new Error('sink down')))
    const iterator = atEof[Symbol.asyncIterator]()
    await iterator.next()
    await expect(iterator.next()).rejects.toThrow('sink down')

    const closed = await opened(new SpySource([ENC.encode('ab'), ENC.encode('cd')]))
    void closed.onSettle(() => Promise.reject(new Error('sink down')))
    await expect(closed.return()).rejects.toThrow('sink down')

    const late = ReadStream.whole(ENC.encode('ab'))
    await expect(late.onSettle(() => Promise.reject(new Error('sink down')))).rejects.toThrow(
      'sink down',
    )
  })

  it('leaves no unhandled rejection when closing the source and a settle callback both fail', async () => {
    const unhandled: unknown[] = []
    const onUnhandled = (reason: unknown): void => {
      unhandled.push(reason)
    }
    process.on('unhandledRejection', onUnhandled)
    try {
      const source: AsyncIterator<Uint8Array> = {
        next: () => Promise.resolve({ done: false, value: ENC.encode('b') }),
        return: () => Promise.reject(new Error('close failed')),
      }
      const stream = new ReadStream(ENC.encode('a'), source)
      void stream.onSettle(() => Promise.reject(new Error('sink down')))
      await expect(stream.return()).rejects.toThrow()
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(unhandled).toEqual([])
    } finally {
      process.off('unhandledRejection', onUnhandled)
    }
  })
})

describe('ReadStream settling once', () => {
  it('resolves a second return after the settling return rejected with a failed callback', async () => {
    const source = new SpySource([ENC.encode('ab'), ENC.encode('cd')])
    const stream = await opened(source)
    void stream.onSettle(() => Promise.reject(new Error('sink down')))
    await expect(stream.return()).rejects.toThrow('sink down')
    expect(source.closed).toBe(true)
    await expect(stream.return()).resolves.toEqual({ done: true, value: undefined })
    await expect(stream.next()).resolves.toEqual({ done: true, value: undefined })
  })

  it('resolves a return after the pull that settled at EOF rejected with a failed callback', async () => {
    const stream = await opened(new SpySource([ENC.encode('ab')]))
    void stream.onSettle(() => Promise.reject(new Error('sink down')))
    await stream.next()
    await expect(stream.next()).rejects.toThrow('sink down')
    await expect(stream.return()).resolves.toEqual({ done: true, value: undefined })
    await expect(stream.next()).resolves.toEqual({ done: true, value: undefined })
  })

  it('rejects only one of two concurrent returns with a failed callback', async () => {
    const stream = await opened(new SpySource([ENC.encode('ab'), ENC.encode('cd')]))
    const calls: number[] = []
    void stream.onSettle((moved) => {
      calls.push(moved)
      return Promise.reject(new Error('sink down'))
    })
    const outcomes = await Promise.allSettled([stream.return(), stream.return()])
    expect(outcomes.map((o) => o.status).sort()).toEqual(['fulfilled', 'rejected'])
    expect(calls).toEqual([2])
  })
})

describe('ReadStream collected unclosed', () => {
  it.skipIf(collectGarbage === undefined)(
    'settles with the partial count once collected (needs a gc the runtime exposes)',
    async () => {
      const settled: number[] = []
      const drained: number[] = []
      const pullAndDrop = async (): Promise<void> => {
        const partial = await opened(
          new SpySource([ENC.encode('ab'), ENC.encode('cd'), ENC.encode('ef')]),
        )
        void partial.onSettle((moved) => settled.push(moved))
        expect(DEC.decode((await partial.next()).value as Uint8Array)).toBe('ab')
        expect(DEC.decode((await partial.next()).value as Uint8Array)).toBe('cd')
        const whole = await opened(new SpySource([ENC.encode('abc')]))
        void whole.onSettle((moved) => drained.push(moved))
        await collect(whole)
      }
      await pullAndDrop()
      expect(settled).toEqual([])
      expect(drained).toEqual([3])
      expect(await collectedWithin(() => settled.length > 0)).toBe(true)
      expect(settled).toEqual([4])
      expect(drained).toEqual([3])
    },
  )

  it.skipIf(collectGarbage === undefined)(
    'reports a settle callback that fails after collection instead of leaving it unhandled (needs a gc the runtime exposes)',
    async () => {
      const unhandled: unknown[] = []
      const onUnhandled = (reason: unknown): void => {
        unhandled.push(reason)
      }
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      process.on('unhandledRejection', onUnhandled)
      try {
        const pullAndDrop = async (): Promise<void> => {
          const stream = await opened(new SpySource([ENC.encode('ab'), ENC.encode('cd')]))
          void stream.onSettle(() => Promise.reject(new Error('sink down')))
          await stream.next()
        }
        await pullAndDrop()
        expect(await collectedWithin(() => warn.mock.calls.length > 0)).toBe(true)
        expect(String(warn.mock.calls[0]?.[0])).toContain('sink down')
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(unhandled).toEqual([])
      } finally {
        process.off('unhandledRejection', onUnhandled)
        warn.mockRestore()
      }
    },
  )
})

describe('ReadStream settle callbacks', () => {
  it('runs every callback even when one throws synchronously, and rejects with it', async () => {
    const stream = await opened(new SpySource([ENC.encode('a'), ENC.encode('b')]))
    const seen: number[] = []
    void stream.onSettle(() => {
      throw new Error('broken callback')
    })
    void stream.onSettle((moved) => {
      seen.push(moved)
    })
    await expect(stream.return()).rejects.toThrow('broken callback')
    expect(seen).toEqual([1])
  })
})

describe('a cap met at a chunk end', () => {
  it.each([
    ['bytes', new Limit({ maxBytes: 4 }), ['abcd', 'efgh'], ['abcd']],
    ['lines', new Limit({ maxLines: 1 }), ['a\n', 'b\n'], ['a\n']],
    ['both', new Limit({ maxBytes: 10, maxLines: 1 }), ['a\n', 'bc'], ['a\n']],
  ] as const)('closes without pulling again (%s)', async (_name, limit, chunks, kept) => {
    const spy = new SpySource(chunks.map((c) => ENC.encode(c)))
    const stream = await opened(spy)
    stream.cap(limit)
    const out = await collect(stream)
    expect(out.map((c) => new TextDecoder().decode(c))).toEqual(kept)
    expect(spy.pulls).toBe(1)
    expect(spy.closed).toBe(true)
  })

  it('ends the read without waiting on a backend that never answers again', async () => {
    const spy = new SpySource([ENC.encode('abcd'), ENC.encode('efgh')])
    const first = await spy.next()
    let asked = false
    const stalled: AsyncIterator<Uint8Array> = {
      next: () => {
        asked = true
        return new Promise<IteratorResult<Uint8Array>>(() => undefined)
      },
      return: () => spy.return(),
    }
    const stream = new ReadStream(first.value as Uint8Array, stalled)
    stream.cap(new Limit({ maxBytes: 4 }))
    const out = await collect(stream)
    expect(out).toEqual([ENC.encode('abcd')])
    expect(asked).toBe(false)
    expect(spy.closed).toBe(true)
  })
})
