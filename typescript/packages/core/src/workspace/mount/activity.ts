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

import { CachableAsyncIterator } from '../../io/cachable_iterator.ts'
import type { ByteSource } from '../../io/types.ts'
import { KeyLock } from '../../cache/lock.ts'

/** Calls and streams sharing one VFS, including its removed aliases. */
export class VFSActivity {
  private count = 0
  private waiters: (() => void)[] = []

  acquire(): () => void {
    this.count++
    let released = false
    return () => {
      if (released) return
      released = true
      this.count--
      if (this.count === 0) {
        for (const resolve of this.waiters.splice(0)) resolve()
      }
    }
  }

  wait(): Promise<void> {
    if (this.count === 0) return Promise.resolve()
    return new Promise((resolve) => {
      this.waiters.push(resolve)
    })
  }

  hold(source: ByteSource): ByteSource {
    if (source instanceof Uint8Array) return source
    if (source instanceof CachableAsyncIterator) {
      if (source.exhausted) return source
      source.wrapSource((inner) => new ActivityStream(inner, this.acquire()))
      return source
    }
    return new ActivityStream(source, this.acquire())
  }
}

// A stream dropped without a close would keep its mount busy for good,
// and unmount waits on that count with no bound; collection is the last
// point anything could still pull from it, so the hold goes with it. The
// registry holds only the release: anything that reaches the stream (a
// command's output can close over the result that holds it) would keep
// it alive for good. JS never finalizes a generator, so the backend of a
// stream dropped here is not closed; a streamed read the door hands out
// closes its backend itself when it is collected (ReadStream). Python's
// loop closes a collected generator, so its `_releasing` does both.
const COLLECTED = new FinalizationRegistry<() => void>((release) => {
  release()
})

/**
 * Explicit return releases even a stream that was never pulled, and a
 * stream that is dropped unclosed releases when it is collected.
 * Mirrors Python's `ActivityStream`.
 */
class ActivityStream implements AsyncIterableIterator<Uint8Array> {
  private readonly source: AsyncIterator<Uint8Array>
  private readonly pullLock = new KeyLock()
  constructor(
    source: AsyncIterable<Uint8Array>,
    private readonly release: () => void,
  ) {
    this.source = source[Symbol.asyncIterator]()
    COLLECTED.register(this, release, this)
  }
  [Symbol.asyncIterator](): AsyncIterableIterator<Uint8Array> {
    return this
  }
  next(): Promise<IteratorResult<Uint8Array>> {
    return this.pullLock.withLock('', async () => {
      try {
        const step = await this.source.next()
        if (step.done === true) this.done()
        return step
      } catch (error) {
        this.done()
        throw error
      }
    })
  }
  return(): Promise<IteratorResult<Uint8Array>> {
    return this.pullLock.withLock('', async () => {
      try {
        await this.source.return?.()
        return { done: true, value: undefined }
      } finally {
        this.done()
      }
    })
  }
  private done(): void {
    COLLECTED.unregister(this)
    this.release()
  }
}
