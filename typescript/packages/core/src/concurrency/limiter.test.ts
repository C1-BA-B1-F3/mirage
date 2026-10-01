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
import { ConcurrencyLimiter, boundedMap } from './limiter.ts'

interface ConcurrencyState {
  active: number
  peak: number
}

async function holdPermit(
  limiter: ConcurrencyLimiter,
  state: ConcurrencyState,
  entered: string[],
  gate: Promise<void>,
): Promise<void> {
  const release = await limiter.acquire()
  state.active += 1
  state.peak = Math.max(state.peak, state.active)
  entered.push('in')
  try {
    await gate
  } finally {
    state.active -= 1
    release()
  }
}

describe('ConcurrencyLimiter', () => {
  it.each([[0], [-1]])('rejects a non-positive capacity (%i)', (capacity) => {
    expect(() => new ConcurrencyLimiter(capacity)).toThrow('at least 1')
  })

  it('limits concurrent operations to the capacity', async () => {
    const limiter = new ConcurrencyLimiter(2)
    const state: ConcurrencyState = { active: 0, peak: 0 }
    const entered: string[] = []
    let open = (): void => undefined
    const gate = new Promise<void>((resolve) => {
      open = resolve
    })

    const held = Array.from({ length: 5 }, () => holdPermit(limiter, state, entered, gate))
    await Promise.resolve()
    await Promise.resolve()
    expect(entered.length).toBe(2)

    open()
    await Promise.all(held)
    expect(state.peak).toBe(2)
  })

  it('a throwing holder still returns its permit', async () => {
    const limiter = new ConcurrencyLimiter(1)
    const release = await limiter.acquire()
    try {
      throw new Error('boom')
    } catch {
      release()
    }
    const second = await limiter.acquire()
    expect(typeof second).toBe('function')
  })

  // The bug the hand-off in `release` exists to prevent. Returning the
  // permit to the pool before waking the waiter leaves it visible for the
  // rest of that tick, so a caller arriving in the same tick takes it --
  // and then the woken waiter decrements too, and both run at once. The
  // late acquire has to happen in the same tick as the release, which is
  // why this drives the limiter directly instead of through holdPermit.
  it('a caller arriving during a release cannot barge past the queue', async () => {
    const limiter = new ConcurrencyLimiter(1)
    const first = await limiter.acquire()

    let queuedGranted = false
    const queued = limiter.acquire().then((release) => {
      queuedGranted = true
      return release
    })

    first()
    let lateGranted = false
    const late = limiter.acquire().then((release) => {
      lateGranted = true
      return release
    })

    await Promise.resolve()
    await Promise.resolve()
    expect(queuedGranted).toBe(true)
    expect(lateGranted).toBe(false)
    ;(await queued)()
    ;(await late)()
  })

  it('releasing twice does not inflate the permit count', async () => {
    const limiter = new ConcurrencyLimiter(1)
    const release = await limiter.acquire()
    release()
    release()

    const state: ConcurrencyState = { active: 0, peak: 0 }
    const entered: string[] = []
    await Promise.all([
      holdPermit(limiter, state, entered, Promise.resolve()),
      holdPermit(limiter, state, entered, Promise.resolve()),
    ])
    expect(state.peak).toBe(1)
  })
})

it('boundedMap stops admitting work and joins active operations on failure', async () => {
  let enter!: () => void
  let release!: () => void
  const entered = new Promise<void>((resolve) => {
    enter = resolve
  })
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const admitted: number[] = []
  let finished = false
  const run = boundedMap(
    [0, 1, 2, 3],
    async (value) => {
      admitted.push(value)
      if (value === 0) {
        await entered
        throw new Error('download failed')
      }
      enter()
      await gate
      return value
    },
    2,
  )
  const checked = expect(run)
    .rejects.toThrow('download failed')
    .then(() => {
      finished = true
    })
  await entered
  await Promise.resolve()
  await Promise.resolve()
  expect(finished).toBe(false)
  expect(admitted).toEqual([0, 1])
  release()
  await checked
  expect(admitted).toEqual([0, 1])
  expect(await boundedMap([3, 1, 2], (x) => Promise.resolve(x * 2), 2)).toEqual([6, 2, 4])
})
