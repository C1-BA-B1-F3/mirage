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

import { STDIN_NAME } from './types.ts'

// The most bytes one read of jq's input reader takes (jq 1.8's util.c):
// fgets into a 4096-byte buffer, less the four bytes it keeps for UTF-8
// and the NUL. A piece that would end inside a character reads on to the
// end of it, and the reader counts a line once it reads the piece that
// ends in the newline.
export const READ_CHUNK = 4091

// The characters that complete a value the moment the parser reads them.
// A number or a literal is complete only at the character after it.
const CLOSERS = '"]}'

/**
 * Where jq's parser holds the whole of a value that ends just before
 * `stop`: at its closing quote or bracket, or else at the delimiter after
 * it, which is `text.length` at the end of the input.
 */
export function valueEnd(text: string, stop: number): number {
  return CLOSERS.includes(text.charAt(stop - 1)) ? stop - 1 : stop
}

function ascii(text: string): boolean {
  for (let i = 0; i < text.length; i += 1) if (text.charCodeAt(i) > 0x7f) return false
  return true
}

function utf8Width(point: number): number {
  return point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4
}

/**
 * Where the last piece of the line `text.slice(start, stop)` (`stop` just
 * past its newline) begins, the piece jq's reader counts the line at.
 */
function lastPiece(text: string, start: number, stop: number): number {
  // No character takes more than four bytes, so a short line is one piece.
  if (stop - start <= READ_CHUNK / 4) return start
  const line = text.slice(start, stop)
  if (ascii(line)) {
    return start + Math.floor((stop - start - 1) / READ_CHUNK) * READ_CHUNK
  }
  let piece = start
  let size = 0
  let i = start
  for (const ch of line) {
    size += utf8Width(ch.codePointAt(0) ?? 0)
    i += ch.length
    if (size >= READ_CHUNK && i < stop) {
      piece = i
      size = 0
    }
  }
  return piece
}

/**
 * How many lines jq's reader has counted by the time it holds each index
 * in `ats` (in order, with `text.length` for the end of the input).
 *
 * The reader counts a newline once it has read the piece that ends in it,
 * and it reads a line whole unless the line runs past READ_CHUNK bytes, so
 * a value inside a long line reads as the line before it until the reader
 * holds the line's last piece.
 */
export function linesRead(text: string, ats: readonly number[]): number[] {
  const counts: number[] = []
  let total = -1
  // The newlines before `start`, the line holding the last index asked
  // about, which is `prev`; `last` is where that line's last piece begins,
  // and -1 until it is looked up.
  let newlines = 0
  let start = 0
  let prev = 0
  let last = -1
  let endsLine = false
  for (const at of ats) {
    if (at >= text.length) {
      if (total < 0) total = text.split('\n').length - 1
      counts.push(total)
      continue
    }
    if (at < prev) {
      newlines = 0
      start = 0
      prev = 0
      last = -1
    }
    for (let i = text.indexOf('\n', prev); i !== -1 && i < at; i = text.indexOf('\n', i + 1)) {
      newlines += 1
      start = i + 1
      last = -1
    }
    prev = at
    if (last < 0) {
      const newline = text.indexOf('\n', at)
      endsLine = newline >= 0
      last = lastPiece(text, start, endsLine ? newline + 1 : text.length)
    }
    counts.push(endsLine && at >= last ? newlines + 1 : newlines)
  }
  return counts
}

/**
 * Where jq's reader stands once it has read each document of the input
 * stream, and once it has read all of it, worded the way jq's error
 * reports word it: the input as the command line named it (`<stdin>` for
 * standard input) and the lines read of it.
 *
 * `marks` holds, for each document, its input and the index at which the
 * reader holds all of it. The lines are counted the first time a position
 * is asked for, which for most runs is never.
 */
export class InputPositions {
  private counts: number[] | null = null

  constructor(
    private readonly names: readonly string[],
    private readonly texts: readonly string[],
    private readonly marks: readonly (readonly [number, number])[],
  ) {}

  private lines(): number[] {
    if (this.counts === null) {
      const counts: number[] = []
      let i = 0
      while (i < this.marks.length) {
        const source = this.marks[i]?.[0] ?? 0
        const ats: number[] = []
        while (i < this.marks.length && this.marks[i]?.[0] === source) {
          ats.push(this.marks[i]?.[1] ?? 0)
          i += 1
        }
        counts.push(...linesRead(this.texts[source] ?? '', ats))
      }
      this.counts = counts
    }
    return this.counts
  }

  /**
   * Where the reader stands once it has read one document. One with no
   * input of its own (a slurp of nothing) stands at the end.
   */
  at(doc: number): string {
    const mark = this.marks[doc]
    if (mark === undefined) return this.end()
    return `${this.names[mark[0]] ?? STDIN_NAME}:${String(this.lines()[doc] ?? 0)}`
  }

  /** Where the reader stands once it has read the whole input. */
  end(): string {
    const last = this.names.length - 1
    if (last < 0) return `${STDIN_NAME}:0`
    const newlines = (this.texts[last] ?? '').split('\n').length - 1
    return `${this.names[last] ?? STDIN_NAME}:${String(newlines)}`
  }
}
