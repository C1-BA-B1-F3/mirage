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

import { concat } from '../../io/cachable_iterator.ts'
import { spliceWindow } from '../../utils/ranges.ts'
import { NO_WRITE, planFlush, type FlushKind } from './flush.ts'

/**
 * One buffered whole-file handle.
 *
 * The shape every encoder used to hand-roll: open snapshots the file
 * into a growable buffer, byte-level calls touch only that buffer, and
 * close asks `flushPlan` whether the mount is owed a tail or the whole
 * file. `lowWrite` and `dirty` exist purely to answer that closing
 * question. Mirrors Python's `FileHandle`.
 */
export class FileHandle {
  readonly path: string
  private _buf: Uint8Array
  private _length: number
  pos = 0
  readonly writable: boolean
  readonly baseLen: number
  lowWrite = NO_WRITE
  dirty = false

  constructor(path: string, buf: Uint8Array, writable = false) {
    this.path = path
    this._buf = buf
    this._length = buf.length
    this.writable = writable
    this.baseLen = buf.length
  }

  /** The used bytes of the backing buffer (capacity may exceed this view). */
  get buf(): Uint8Array {
    return this._buf.subarray(0, this._length)
  }

  /**
   * A handle over `data`, positioned by the open mode.
   *
   * Args:
   *   path: guest-absolute virtual path.
   *   data: the file's content at open (empty when the open created
   *     or truncated it).
   *   mode: whether writes are accepted, and whether the position
   *     starts at the end.
   */
  static opened(
    path: string,
    data: Uint8Array,
    mode: { writable: boolean; append: boolean },
  ): FileHandle {
    const handle = new FileHandle(path, data, mode.writable)
    if (mode.append) handle.pos = data.length
    return handle
  }

  /**
   * Read from the position, advancing it by what was read.
   *
   * Args:
   *   size: byte budget; null or negative reads to the end. A
   *     position past the end reads empty and stays.
   */
  read(size: number | null): Uint8Array {
    const end = size === null || size < 0 ? this._length : Math.min(this._length, this.pos + size)
    const chunk = this._buf.slice(this.pos, end)
    this.pos += chunk.length
    return chunk
  }

  /** Read at an explicit offset without moving the position. */
  pread(offset: number, size: number): Uint8Array {
    return this._buf.slice(offset, Math.min(offset + size, this._length))
  }

  /**
   * Grow the backing buffer to at least `needed` bytes, doubling the
   * capacity each time so N appends cost O(N) instead of O(N²).
   */
  private _grow(needed: number): void {
    if (needed <= this._buf.length) return
    let capacity = this._buf.length
    if (capacity === 0) capacity = 4096
    while (capacity < needed) capacity *= 2
    const grown = new Uint8Array(capacity)
    grown.set(this._buf.subarray(0, this._length))
    this._buf = grown
    this._growCount++
  }

  /** Internal counter for tests to verify amortized growth. */
  _growCount = 0

  /**
   * Splice bytes in at an offset without moving the position.
   *
   * Grows the buffer through a zero fill when the offset lies past the
   * end, and keeps the two facts the closing flush plan reads: the
   * lowest offset written and that anything was written at all.
   */
  pwrite(offset: number, data: Uint8Array): void {
    const end = offset + data.length
    this._grow(end)
    if (offset > this._length) this._buf.fill(0, this._length, offset)
    if (end > this._length) this._length = end
    this.lowWrite = Math.min(this.lowWrite, offset)
    this._buf.set(data, offset)
    this.dirty = true
  }

  /** Write at the position, advancing it past the payload. */
  write(data: Uint8Array): void {
    this.pwrite(this.pos, data)
    this.pos += data.length
  }

  /**
   * Move the position, POSIX whence numbering (0 start, 1 position,
   * 2 end). Answers the new position, or null when the whence is
   * unknown or the target would be negative (the position is then
   * untouched).
   */
  seek(offset: number, whence: number): number | null {
    const base = whence === 0 ? 0 : whence === 1 ? this.pos : whence === 2 ? this._length : null
    if (base === null || base + offset < 0) return null
    this.pos = base + offset
    return this.pos
  }

  /**
   * Resize the buffer, zero-filling growth. Either direction rewrites
   * what the file already held (a shrink drops bytes, a zero fill
   * fabricates them), which no tail can express, so the close ships
   * the whole buffer.
   */
  truncate(size: number): void {
    if (size < this._length) {
      this._length = size
    } else {
      this._grow(size)
      if (size > this._length) {
        this._buf.fill(0, this._length, size)
        this._length = size
      }
    }
    this.dirty = true
    this.lowWrite = 0
  }

  /** True when the position sits at or past the end. */
  get eof(): boolean {
    return this.pos >= this._length
  }

  /** The file's length as this handle holds it. */
  get size(): number {
    return this._length
  }

  /** What this handle owes the mount at close. */
  flushPlan(): [FlushKind, Uint8Array] {
    return planFlush(this.baseLen, this.lowWrite, this.buf)
  }
}

/**
 * Buffered (offset, payload) writes as the fewest pwrites that leave a file
 * as the writes did, in arrival order.
 *
 * The kernel adapters buffer each write on its handle and owe the mount the
 * lot at flush. A write that starts inside the last run, or right at its
 * end, folds into it, so a sequential stream is one run. Any other starts a
 * run of its own; the runs apply in order, so a later run still overwrites
 * what it overlaps of an earlier one.
 *
 * Args:
 *   writes: the buffered writes, in arrival order.
 */
export function writeRuns(writes: readonly [number, Uint8Array][]): [number, Uint8Array][] {
  const runs: { start: number; parts: Uint8Array[]; length: number }[] = []
  for (const [offset, chunk] of writes) {
    const last = runs.at(-1)
    if (last !== undefined && last.start <= offset && offset <= last.start + last.length) {
      const at = offset - last.start
      if (at === last.length) {
        last.parts.push(chunk.slice())
        last.length += chunk.byteLength
        continue
      }
      const merged = spliceWindow(concat(last.parts), at, chunk)
      last.parts = [merged]
      last.length = merged.byteLength
      continue
    }
    runs.push({ start: offset, parts: [chunk.slice()], length: chunk.byteLength })
  }
  return runs.map((run): [number, Uint8Array] => [run.start, concat(run.parts)])
}
