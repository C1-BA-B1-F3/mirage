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
import { materialize } from '../../../io/types.ts'
import { Limit, OnExceed } from '../../../types.ts'
import { CommandTimeoutError } from '../../errors.ts'
import { applyLimit, maybeWithTimeout, runWithTimeout, withPullTimeout } from './limit.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()
const TEN = ENC.encode(Array.from({ length: 10 }, (_, i) => `line${String(i)}\n`).join(''))

async function* stream(data: Uint8Array): AsyncIterable<Uint8Array> {
  await Promise.resolve()
  for (let i = 0; i < data.byteLength; i += 7) {
    yield data.subarray(i, i + 7)
  }
}

async function bytesOf(out: Uint8Array | AsyncIterable<Uint8Array> | null): Promise<Uint8Array> {
  if (out === null) return new Uint8Array()
  return materialize(out)
}

describe('applyLimit', () => {
  it('passes through when limit is null', async () => {
    const [out, io] = await applyLimit(TEN, null)
    expect(await bytesOf(out)).toEqual(TEN)
    expect(io.exitCode).toBe(0)
    expect(io.stderr).toBeNull()
  })

  it('passes through when under limit', async () => {
    const sg = new Limit({ maxLines: 100 })
    const [out, io] = await applyLimit(TEN, sg)
    expect(await bytesOf(out)).toEqual(TEN)
    expect(io.stderr).toBeNull()
  })

  it('truncates by lines', async () => {
    const sg = new Limit({ maxLines: 3 })
    const [out, io] = await applyLimit(TEN, sg)
    expect(DEC.decode(await bytesOf(out))).toBe('line0\nline1\nline2\n')
    expect(io.exitCode).toBe(0)
    expect(DEC.decode(await materialize(io.stderr))).toContain('truncated')
  })

  it('error mode returns null stdout + exit 1', async () => {
    const sg = new Limit({ maxLines: 3, onExceed: OnExceed.ERROR })
    const [out, io] = await applyLimit(TEN, sg)
    expect(out).toBeNull()
    expect(io.exitCode).toBe(1)
    expect(DEC.decode(await materialize(io.stderr))).toContain('truncated')
  })

  it('truncates by bytes', async () => {
    const sg = new Limit({ maxBytes: 10 })
    const [out, io] = await applyLimit(TEN, sg)
    expect(await bytesOf(out)).toEqual(TEN.subarray(0, 10))
    expect(DEC.decode(await materialize(io.stderr))).toContain('truncated')
  })

  it('truncates streaming input early', async () => {
    const sg = new Limit({ maxLines: 2 })
    const [out, io] = await applyLimit(stream(TEN), sg)
    expect(DEC.decode(await bytesOf(out))).toBe('line0\nline1\n')
    expect(DEC.decode(await materialize(io.stderr))).toContain('truncated')
  })
})

it.each([1, 2, 20])('intersects limits and detects exact fits with chunks of %i', async (size) => {
  for (const [text, limit, expected, truncated] of [
    ['a\nb\n', new Limit({ maxLines: 2 }), 'a\nb\n', false],
    ['a\nb\nc\nd\n', new Limit({ maxLines: 2, maxBytes: 7 }), 'a\nb\n', true],
    ['abc', new Limit({ maxLines: 0 }), '', true],
    ['abc', new Limit({ maxBytes: 0 }), '', true],
    ['abc', new Limit({ maxBytes: 3 }), 'abc', false],
    ['a\nb', new Limit({ maxLines: 1 }), 'a\n', true],
  ] as const) {
    async function* source(): AsyncIterable<Uint8Array> {
      for (let at = 0; at < text.length; at += size)
        yield await Promise.resolve(new TextEncoder().encode(text.slice(at, at + size)))
    }
    const [out, io] = await applyLimit(source(), limit)
    expect(new TextDecoder().decode(await materialize(out))).toBe(expected)
    expect((await io.stderrStr()).includes('truncated')).toBe(truncated)
  }
})

describe('withPullTimeout', () => {
  class Paced implements AsyncIterator<Uint8Array> {
    closed = false
    private left: number

    constructor(
      count: number,
      private readonly delayMs: number,
    ) {
      this.left = count
    }

    async next(): Promise<IteratorResult<Uint8Array>> {
      await new Promise((resolve) => setTimeout(resolve, this.delayMs))
      if (this.left === 0) return { done: true, value: undefined }
      this.left--
      return { done: false, value: new TextEncoder().encode('x') }
    }

    return(): Promise<IteratorResult<Uint8Array>> {
      this.closed = true
      return Promise.resolve({ done: true, value: undefined })
    }

    [Symbol.asyncIterator](): AsyncIterator<Uint8Array> {
      return this
    }
  }

  it('raises CommandTimeoutError when one pull exceeds the budget', async () => {
    const err = await materialize(withPullTimeout(new Paced(1, 200), 0.02, 'read')).catch(
      (e: unknown) => e,
    )
    expect(err).toBeInstanceOf(CommandTimeoutError)
    expect((err as Error).message).toBe('read: timed out after 0.02s')
  })

  it('passes chunks through when each pull is fast even if the total exceeds the budget', async () => {
    const out = await materialize(withPullTimeout(new Paced(5, 60), 0.2, 'read'))
    expect(DEC.decode(out)).toBe('xxxxx')
  })

  it('closes the source at the end', async () => {
    const drained = new Paced(2, 0)
    await materialize(withPullTimeout(drained, 1, 'read'))
    expect(drained.closed).toBe(true)
    const stopped = new Paced(5, 0)
    for await (const chunk of withPullTimeout(stopped, 1, 'read')) {
      expect(DEC.decode(chunk)).toBe('x')
      break
    }
    expect(stopped.closed).toBe(true)
  })

  it('closes its source after a pull overruns', async () => {
    const source = new Paced(5, 200)
    await expect(materialize(withPullTimeout(source, 0.02, 'read'))).rejects.toThrow(
      CommandTimeoutError,
    )
    expect(source.closed).toBe(true)
  })

  it('closes the iterator an iterable hands out after a pull overruns', async () => {
    const iterator = new Paced(5, 200)
    const iterable: AsyncIterable<Uint8Array> = { [Symbol.asyncIterator]: () => iterator }
    await expect(materialize(withPullTimeout(iterable, 0.02, 'read'))).rejects.toThrow(
      CommandTimeoutError,
    )
    expect(iterator.closed).toBe(true)
  })

  it('abandons a generator pull that never settles instead of awaiting it', async () => {
    let pulled = false
    let closed = false
    async function* hung(): AsyncGenerator<Uint8Array> {
      try {
        pulled = true
        await new Promise(() => undefined)
        yield new Uint8Array([1])
      } finally {
        closed = true
      }
    }
    const outcome = await settleWithin(materialize(withPullTimeout(hung(), 0.05, 'read')), 2000)
    expect(pulled).toBe(true)
    expect(outcome).toBeInstanceOf(CommandTimeoutError)
    expect((outcome as Error).message).toBe('read: timed out after 0.05s')
    expect(closed).toBe(false)
  })
})

const LATE = Symbol('late')

async function settleWithin(promise: Promise<unknown>, ms: number): Promise<unknown> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const late = new Promise<typeof LATE>((resolve) => {
    timer = setTimeout(() => {
      resolve(LATE)
    }, ms)
  })
  try {
    return await Promise.race([
      promise.then(
        () => null,
        (err: unknown) => err,
      ),
      late,
    ])
  } finally {
    clearTimeout(timer)
  }
}

function backendTimeout(): Error {
  return Object.assign(new Error('connect ETIMEDOUT 10.0.0.1:443'), { code: 'ETIMEDOUT' })
}

describe('a timeout budget and a backend timeout inside it', () => {
  it('runWithTimeout keeps a backend ETIMEDOUT raised inside the budget', async () => {
    const own = backendTimeout()
    const err = await runWithTimeout(Promise.reject(own), 5, 'read').catch((e: unknown) => e)
    expect(err).toBe(own)
    expect(err).not.toBeInstanceOf(CommandTimeoutError)
    expect((err as { code?: string }).code).toBe('ETIMEDOUT')
  })

  it('runWithTimeout still raises CommandTimeoutError on an overrun', async () => {
    const err = await settleWithin(runWithTimeout(new Promise(() => undefined), 0.05, 'read'), 2000)
    expect(err).toBeInstanceOf(CommandTimeoutError)
    expect((err as Error).message).toBe('read: timed out after 0.05s')
  })

  it('withPullTimeout keeps a backend ETIMEDOUT raised inside a pull', async () => {
    const own = backendTimeout()
    async function* failing(): AsyncGenerator<Uint8Array> {
      yield await Promise.resolve(ENC.encode('a'))
      throw own
    }
    const err = await materialize(withPullTimeout(failing(), 5, 'read')).catch((e: unknown) => e)
    expect(err).toBe(own)
    expect(err).not.toBeInstanceOf(CommandTimeoutError)
    expect((err as { code?: string }).code).toBe('ETIMEDOUT')
  })

  it('maybeWithTimeout keeps a backend ETIMEDOUT raised inside the budget and times out an overrun', async () => {
    const own = backendTimeout()
    async function* failing(): AsyncGenerator<Uint8Array> {
      yield await Promise.resolve(ENC.encode('a'))
      throw own
    }
    const kept = maybeWithTimeout(failing(), new Limit({ timeoutSeconds: 5 }), 'cat')
    if (kept === null) throw new Error('expected a stream')
    const err = await materialize(kept).catch((e: unknown) => e)
    expect(err).toBe(own)
    expect((err as { code?: string }).code).toBe('ETIMEDOUT')
    async function* late(): AsyncGenerator<Uint8Array> {
      await new Promise((resolve) => setTimeout(resolve, 300))
      yield ENC.encode('late')
    }
    const slow = maybeWithTimeout(late(), new Limit({ timeoutSeconds: 0.05 }), 'cat')
    if (slow === null) throw new Error('expected a stream')
    expect(await settleWithin(materialize(slow), 2000)).toBeInstanceOf(CommandTimeoutError)
  })
})
