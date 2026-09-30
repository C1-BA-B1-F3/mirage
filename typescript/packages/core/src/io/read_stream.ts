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

import type { Limit } from '../types.ts'

const NEWLINE = 0x0a

/**
 * How much of `chunk` a byte and line cap lets through.
 *
 * The one cut every lazy cap applies, so a capped stream and a capped
 * whole read stop at the same byte. Mirrors Python's `cap_end`.
 */
export function capEnd(chunk: Uint8Array, limit: Limit, emitted: number, lines: number): number {
  let end =
    limit.maxBytes === null
      ? chunk.byteLength
      : Math.min(chunk.byteLength, Math.max(0, limit.maxBytes - emitted))
  if (limit.maxLines === null) return end
  if (lines >= limit.maxLines) return 0
  let seen = lines
  for (let i = 0; i < end; i++) {
    if (chunk[i] === NEWLINE && ++seen === limit.maxLines) {
      end = i + 1
      break
    }
  }
  return end
}

/** Whether a cap lets nothing more through. Mirrors Python's `_cap_spent`. */
function capSpent(limit: Limit, emitted: number, lines: number): boolean {
  return (
    (limit.maxBytes !== null && emitted >= limit.maxBytes) ||
    (limit.maxLines !== null && lines >= limit.maxLines)
  )
}

function countNewlines(chunk: Uint8Array): number {
  let n = 0
  for (const byte of chunk) if (byte === NEWLINE) n++
  return n
}

/**
 * What a read moved, and who is told once it settles. Kept apart from the
 * stream so the finalizer that settles a stream nobody closed holds this,
 * never the stream itself. Mirrors Python's `_Tally`.
 */
class Tally {
  settled = false
  callbacks: ((moved: number) => unknown)[] = []

  constructor(public moved: number) {}

  /**
   * Tell every callback once; null when an earlier call already did.
   * Each runs even if one before it failed, synchronously or not, and
   * the first failure is what the returned promise rejects with.
   */
  settle(): Promise<unknown> | null {
    if (this.settled) return null
    this.settled = true
    const callbacks = this.callbacks
    this.callbacks = []
    return Promise.all(
      callbacks.map(
        (callback) =>
          new Promise((resolve) => {
            resolve(callback(this.moved))
          }),
      ),
    )
  }
}

interface Abandoned {
  source: AsyncIterator<Uint8Array>
  tally: Tally
}

// A stream collected unclosed still closes its backend (JS never finalizes
// the generator underneath, so nothing else would) and then settles, so
// the read is recorded with what it moved. What the registry holds cannot
// reach the stream: the door builds the stream over a backend chain that
// never refers to it. Nobody is left to hand a failure to, so it is
// reported here.
const COLLECTED = new FinalizationRegistry<Abandoned>((held) => {
  void Promise.resolve()
    .then(() => held.source.return?.())
    .then(() => held.tally.settle())
    .catch((err: unknown) => {
      console.warn(`closing a collected read stream failed: ${String(err)}`)
      return held.tally.settle()
    })
    .catch((err: unknown) => {
      console.warn(`read stream settled after collection with an error: ${String(err)}`)
    })
})

/**
 * A read the op door hands out while it is still arriving.
 *
 * The door pulls the first chunk before it returns one, so a read that
 * cannot open (a missing path, a directory, a refusal) fails at the
 * call exactly as a whole read does; the rest comes from the backend as
 * the consumer pulls it. The stream counts what the backend moved, cuts
 * at a truncating cap, and settles once: when the bytes end, when a
 * pull fails, on `return()`, which a consumer that stops early calls
 * (a `break` out of `for await` does) to release the backend and the
 * mount serving it, or when it is collected unclosed, so the read is
 * recorded with what it moved either way. Mirrors Python's `ReadStream`.
 */
export class ReadStream implements AsyncIterableIterator<Uint8Array> {
  private first: Uint8Array | null
  private source: AsyncIterator<Uint8Array> | null
  private limit: Limit | null = null
  private readonly tally: Tally
  private emitted = 0
  private lines = 0

  constructor(first: Uint8Array | null, source: AsyncIterator<Uint8Array> | null) {
    this.first = first
    this.source = source
    this.tally = new Tally(first !== null ? first.byteLength : 0)
    if (source === null) void this.tally.settle()
    else COLLECTED.register(this, { source, tally: this.tally }, this)
  }

  /** A read already in hand, handed out as one chunk. */
  static whole(data: Uint8Array): ReadStream {
    return new ReadStream(data, null)
  }

  /** Truncate what is handed out from here on at `limit`. */
  cap(limit: Limit): void {
    this.limit = limit
  }

  /**
   * Call `callback` with the bytes moved once the read settles; a read
   * that has already settled answers at once, and the returned promise
   * is the callback's. A callback that returns a promise (the facade's
   * record, which awaits its sink) is awaited by the pull or `return()`
   * that settles the read, so its failure reaches that caller, once.
   * The callback must not hold the stream: it rides the registry that
   * settles a stream nobody closed, and would keep that stream alive.
   */
  onSettle(callback: (moved: number) => unknown): Promise<unknown> {
    if (this.tally.settled) return Promise.resolve(callback(this.tally.moved))
    this.tally.callbacks.push(callback)
    return Promise.resolve()
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<Uint8Array> {
    return this
  }

  async next(): Promise<IteratorResult<Uint8Array>> {
    let chunk = this.first
    this.first = null
    if (chunk === null) {
      const source = this.source
      if (source === null) return { done: true, value: undefined }
      let step: IteratorResult<Uint8Array>
      try {
        step = await source.next()
      } catch (err) {
        this.source = null
        await this.settle()
        throw err
      }
      if (step.done === true) {
        this.source = null
        await this.settle()
        return { done: true, value: undefined }
      }
      chunk = step.value
      this.tally.moved += chunk.byteLength
    }
    if (this.limit === null) return { done: false, value: chunk }
    const end = capEnd(chunk, this.limit, this.emitted, this.lines)
    const kept = chunk.subarray(0, end)
    this.emitted += end
    this.lines += countNewlines(kept)
    // A cap met exactly at a chunk's end closes now: pulling the backend
    // again only to cut the next chunk to nothing would make a finished
    // read wait on (or fail with) one more backend call.
    if (end < chunk.byteLength || capSpent(this.limit, this.emitted, this.lines)) {
      await this.return()
      if (kept.byteLength === 0) return { done: true, value: undefined }
    }
    return { done: false, value: kept }
  }

  /** Stop the read: close the backend and settle what it moved. */
  async return(): Promise<IteratorResult<Uint8Array>> {
    this.first = null
    const source = this.source
    this.source = null
    try {
      await source?.return?.()
    } finally {
      await this.settle()
    }
    return { done: true, value: undefined }
  }

  private async settle(): Promise<void> {
    COLLECTED.unregister(this)
    await this.tally.settle()
  }
}
