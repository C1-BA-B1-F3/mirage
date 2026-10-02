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

import { FsError } from '@deepseek-ai/dsh-fs'
import type { SubprocessOutputRead, SubprocessOutputReader } from '@deepseek-ai/dsh-subprocess'

const BINARY_SAMPLE_BYTES = 8192

// dsh text semantics: a NUL in the leading sample or invalid UTF-8 is a
// binary file, refused as FS_NOT_TEXT rather than decoded lossily (the
// mirage facade's readFileText decodes with fatal: false, which the dsh
// seam contract forbids).
export function decodeStrictText(bytes: Uint8Array, displayPath: string): string {
  if (bytes.subarray(0, BINARY_SAMPLE_BYTES).includes(0)) {
    throw new FsError(`cannot read "${displayPath}": binary file`, 'FS_NOT_TEXT')
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch (error: unknown) {
    throw new FsError(`cannot read "${displayPath}": invalid UTF-8 text`, 'FS_NOT_TEXT', {
      cause: error,
    })
  }
}

export function normalizeLineEndings(value: string): string {
  return value.replaceAll('\r\n', '\n')
}

// CRLF-majority sniff over a bounded sample, the same heuristic dsh's own
// backends use to keep a rewritten file in its original line-ending style.
export function detectsCrlf(value: string): boolean {
  const sample = value.slice(0, 4096)
  const crlf = sample.split('\r\n').length - 1
  const lf = sample.split('\n').length - 1 - crlf
  return crlf > lf
}

export function restoreLineEndings(value: string, crlf: boolean): string {
  return crlf ? normalizeLineEndings(value).replaceAll('\n', '\r\n') : value
}

function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) return 0
  let count = 0
  let index = haystack.indexOf(needle)
  while (index !== -1) {
    count++
    index = haystack.indexOf(needle, index + needle.length)
  }
  return count
}

// Literal replacement with dsh's edit taxonomy: zero matches and an empty
// oldString are FS_EDIT_NOT_FOUND, several matches without replaceAll is
// FS_AMBIGUOUS_EDIT.
export function applyLiteralEdit(
  content: string,
  oldString: string,
  newString: string,
  replaceAll: boolean,
  displayPath: string,
): string {
  const matches = countOccurrences(content, oldString)
  if (matches === 0) {
    throw new FsError(`cannot edit "${displayPath}": oldString not found`, 'FS_EDIT_NOT_FOUND')
  }
  if (matches > 1 && !replaceAll) {
    throw new FsError(
      `cannot edit "${displayPath}": oldString matches ${String(matches)} locations; pass replaceAll or a longer unique string`,
      'FS_AMBIGUOUS_EDIT',
    )
  }
  return replaceAll
    ? content.replaceAll(oldString, newString)
    : content.replace(oldString, newString)
}

// The first index at or after `from` that starts a UTF-8 sequence, so a tail
// taken from there decodes as characters rather than as replacement marks.
function charBoundary(bytes: Uint8Array, from: number): number {
  let start = from
  while (start < bytes.byteLength && ((bytes[start] ?? 0) & 0xc0) === 0x80) start++
  return start
}

// The end of the last whole UTF-8 sequence, so a read of a stream still
// arriving leaves a character it holds only part of for the next read.
function charEnd(bytes: Uint8Array): number {
  const end = bytes.byteLength
  for (let back = 1; back <= Math.min(4, end); back++) {
    const byte = bytes[end - back] ?? 0
    if ((byte & 0xc0) === 0x80) continue
    const width = byte >= 0xf0 ? 4 : byte >= 0xe0 ? 3 : byte >= 0xc0 ? 2 : 1
    return width > back ? end - back : end
  }
  return end
}

// Byte-accurate tail cap: keep the LAST maxBytes bytes of the encoded text,
// re-aligned to a UTF-8 sequence boundary so the kept tail still decodes.
export function tailCap(text: string, maxBytes: number): { text: string; truncated: boolean } {
  const bytes = new TextEncoder().encode(text)
  if (bytes.byteLength <= maxBytes) return { text, truncated: false }
  const start = charBoundary(bytes, bytes.byteLength - maxBytes)
  return {
    text: new TextDecoder('utf-8', { fatal: false }).decode(bytes.subarray(start)),
    truncated: true,
  }
}

/**
 * A bounded backlog of output bytes: the newest `budget` bytes, with the
 * oldest dropped as they overflow.
 *
 * Held as bytes rather than as a string because the string form had to
 * re-encode everything already buffered on every append to measure it,
 * which is quadratic in a command's output and lands on the same event
 * loop that serves the workspace. Appending here costs the chunk, not
 * the backlog.
 */
export class TailBuffer {
  private readonly budget: number
  private parts: Uint8Array[] = []
  private bytes = 0

  constructor(budget: number) {
    this.budget = budget
  }

  /**
   * Append a chunk, dropping the oldest bytes that no longer fit.
   *
   * @param data the bytes to append.
   * @returns true when bytes were dropped to make room.
   */
  append(data: Uint8Array): boolean {
    this.parts.push(data)
    this.bytes += data.byteLength
    if (this.bytes <= this.budget) return false
    let excess = this.bytes - this.budget
    while (excess > 0) {
      const head = this.parts[0]
      if (head === undefined) break
      if (head.byteLength <= excess) {
        this.parts.shift()
        excess -= head.byteLength
        this.bytes -= head.byteLength
      } else {
        this.parts[0] = head.subarray(excess)
        this.bytes -= excess
        excess = 0
      }
    }
    return true
  }

  /** How many bytes are held. */
  get size(): number {
    return this.bytes
  }

  /**
   * Everything held, joined, leaving it held.
   *
   * @returns the held bytes, oldest first.
   */
  peek(): Uint8Array {
    const joined = new Uint8Array(this.bytes)
    let at = 0
    for (const part of this.parts) {
      joined.set(part, at)
      at += part.byteLength
    }
    return joined
  }

  /**
   * Drain everything held, decoded as text.
   *
   * The head may sit mid-character, since dropping is byte-exact, so it
   * is re-aligned before decoding rather than rendered as a replacement
   * mark.
   *
   * @returns the buffered text; the buffer is left empty.
   */
  take(): string {
    if (this.parts.length === 0) return ''
    const joined = this.peek()
    this.parts = []
    this.bytes = 0
    return new TextDecoder('utf-8', { fatal: false }).decode(
      joined.subarray(charBoundary(joined, 0)),
    )
  }
}

/**
 * One collected output stream as a whole-stream offset reader over its
 * bounded tail: `readFrom(0)` after it settles is the batch result, and an
 * offset that slid out of the tail reads `lossy` with the whole tail.
 */
export class StreamTail implements SubprocessOutputReader {
  private readonly tail: TailBuffer
  private offset = 0
  private ended = false

  constructor(max: number) {
    this.tail = new TailBuffer(max)
  }

  /** Whether the tail has lost its head, so the stream is truncated. */
  get truncated(): boolean {
    return this.offset > this.tail.size
  }

  append(chunk: Uint8Array): void {
    this.offset += chunk.byteLength
    this.tail.append(chunk)
  }

  /** Mark the stream finished, so a read decodes through its last byte. */
  end(): void {
    this.ended = true
  }

  readFrom(fromByte: number): SubprocessOutputRead {
    if (!Number.isSafeInteger(fromByte) || fromByte < 0 || fromByte > this.offset)
      throw new Error('invalid output offset')
    const bytes = this.tail.peek()
    const start = this.offset - bytes.byteLength
    let from = Math.max(0, fromByte - start)
    // A tail that lost its head can begin mid-character; the reader is
    // handed whole characters only, so the stray continuation bytes go.
    if (from === 0 && start > 0) from = charBoundary(bytes, 0)
    // A stream still arriving can stop mid-character too: the read ends
    // before it, so the next read decodes it whole.
    const stop = Math.max(from, this.ended ? bytes.byteLength : charEnd(bytes))
    return {
      text: new TextDecoder('utf-8', { fatal: false }).decode(bytes.subarray(from, stop)),
      nextOffset: start + stop,
      lossy: fromByte < start,
    }
  }
}
