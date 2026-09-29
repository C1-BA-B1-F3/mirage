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

import { compilePosixRegex } from '../../utils/posix.ts'
import { encodeText } from '../../shell/bytes.ts'
import { byteOffset } from '../../shell/helpers.ts'

const DEC_FATAL = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })

/**
 * The input's bytes as text a byte offset can be counted back out of.
 *
 * The whole family holds a line as text, so every byte offset it prints is a
 * code-unit index converted back. That only answers GNU's number when the
 * conversion round-trips, which `TextDecoder`'s replacement does not: an
 * invalid byte becomes U+FFFD, three bytes wide, so a `-bo` match offset
 * inside such a line ran ahead of GNU's. A byte above ASCII is carried as its
 * surrogate escape instead, the convention `byteOffset` in `shell/helpers.ts`
 * already assumes through `encodeText`, and the twin of `decode_line` in
 * `grep_offsets.py`.
 */
export function decodeLine(raw: Uint8Array): string {
  try {
    return DEC_FATAL.decode(raw)
  } catch (error) {
    if (!(error instanceof TypeError)) throw error
  }
  const parts: string[] = []
  const units = new Uint16Array(Math.min(raw.length, 8192))
  let used = 0
  for (let i = 0; i < raw.length; ) {
    const byte = raw[i] ?? 0
    const second = raw[i + 1] ?? 0
    const third = raw[i + 2] ?? 0
    const fourth = raw[i + 3] ?? 0
    let code = byte < 0x80 ? byte : 0xdc00 + byte
    let width = 1
    // Reject overlong encodings, surrogate code points and values above
    // U+10FFFF. An invalid sequence escapes only its first byte, just as
    // Python's surrogateescape does, then retries at the following byte.
    if (byte >= 0xc2 && byte <= 0xdf && second >= 0x80 && second <= 0xbf) {
      code = ((byte & 0x1f) << 6) | (second & 0x3f)
      width = 2
    } else if (
      byte >= 0xe0 &&
      byte <= 0xef &&
      second >= (byte === 0xe0 ? 0xa0 : 0x80) &&
      second <= (byte === 0xed ? 0x9f : 0xbf) &&
      third >= 0x80 &&
      third <= 0xbf
    ) {
      code = ((byte & 0x0f) << 12) | ((second & 0x3f) << 6) | (third & 0x3f)
      width = 3
    } else if (
      byte >= 0xf0 &&
      byte <= 0xf4 &&
      second >= (byte === 0xf0 ? 0x90 : 0x80) &&
      second <= (byte === 0xf4 ? 0x8f : 0xbf) &&
      third >= 0x80 &&
      third <= 0xbf &&
      fourth >= 0x80 &&
      fourth <= 0xbf
    ) {
      code = ((byte & 7) << 18) | ((second & 0x3f) << 12) | ((third & 0x3f) << 6) | (fourth & 0x3f)
      width = 4
    }
    if (code > 0xffff) {
      code -= 0x10000
      units[used++] = 0xd800 + (code >> 10)
      units[used++] = 0xdc00 + (code & 0x3ff)
    } else {
      units[used++] = code
    }
    i += width
    if (used >= units.length - 1) {
      parts.push(String.fromCharCode(...units.subarray(0, used)))
      used = 0
    }
  }
  if (used > 0) parts.push(String.fromCharCode(...units.subarray(0, used)))
  return parts.join('')
}

/** Text back to the bytes `decodeLine` read it from. */
export function encodeLine(text: string): Uint8Array {
  return encodeText(text)
}

/**
 * Byte offset of each line's own first byte within the whole input.
 *
 * A line iterator strips the terminator, so the accumulator advances by one
 * more than the line's own length. The extra byte past the last line is never
 * read, which is why a file with no final newline still reports a correct
 * offset for every line it does have. The lines must have come from
 * `decodeLine`; a lossily decoded one cannot be counted back.
 */
export function lineOffsets(lines: readonly string[]): number[] {
  const offsets: number[] = []
  let position = 0
  for (const line of lines) {
    offsets.push(position)
    position += encodeText(line).length + 1
  }
  return offsets
}

/**
 * Where a match begins in bytes, given its character index.
 *
 * The pattern engine reports a code-unit index because both hosts hold a line
 * as text; GNU reports a byte count and reports the same number under C and
 * C.utf8, so the index is converted rather than printed.
 */
export function matchOffset(lineStart: number, line: string, index: number): number {
  return lineStart + byteOffset(line, index)
}

/**
 * Every match of a pattern in a line, found as ripgrep finds them.
 *
 * ripgrep iterates matches the way Rust's regex crate does: after an empty
 * match the search resumes one character on, and an empty match where the
 * previous match ended is skipped, so `b*` on `abc` is three matches. Returns
 * each match's code-unit index and text. Mirrors Python's rust_matches.
 */
export function rustMatches(pat: RegExp, line: string): [number, string][] {
  const re = compilePosixRegex(pat.source, `${pat.flags.replace(/[gy]/g, '')}g`)
  const matches: [number, string][] = []
  let pos = 0
  let lastEnd = -1
  while (pos <= line.length) {
    re.lastIndex = pos
    const m = re.exec(line)
    if (m === null) break
    const end = m.index + m[0].length
    if (m[0] === '') {
      // One character on, which a surrogate pair is too.
      pos = end + ((line.codePointAt(end) ?? 0) > 0xffff ? 2 : 1)
      if (end === lastEnd) continue
    } else {
      pos = end
    }
    lastEnd = end
    matches.push([m.index, m[0]])
  }
  return matches
}

/**
 * What ripgrep's -o prints for one line, one piece per output line: each
 * match, empty ones included (`rustMatches`), or the whole line when nothing
 * in it matches, which is how ripgrep prints an inverted selection and a
 * context line under -o (14.1.1). Mirrors Python's rg_pieces.
 */
export function rgPieces(pat: RegExp, line: string): [number, string][] {
  const matches = rustMatches(pat, line)
  return matches.length > 0 ? matches : [[0, line]]
}

/** Incremental byte offsets for monotonically increasing match indices on one line. */
export class MatchOffsets {
  private index = 0

  constructor(
    private position: number,
    private readonly line: string,
  ) {}

  at(index: number): number {
    // A non-Unicode regex can stop between a surrogate pair. Keep that pair
    // for the next step, while matching the old prefix encoder's replacement.
    const before = this.line.charCodeAt(index - 1)
    const after = this.line.charCodeAt(index)
    const split = before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff
    const end = split ? index - 1 : index
    this.position += byteOffset(this.line.slice(this.index, end), end - this.index)
    this.index = end
    return this.position + (split ? 3 : 0)
  }
}

/**
 * grep's line-number and byte-offset fields, in GNU's fixed order.
 *
 * GNU prints FILENAME, then LINE NUMBER, then BYTE OFFSET, whatever order the
 * flags were given in, and picks the separator once per line: a context line
 * renders every field with `-` where a selected line uses `:`.
 */
export function prefixOf(number: number | null, offset: number | null, selected = true): string {
  const separator = selected ? ':' : '-'
  let fields = ''
  if (number !== null) fields += String(number) + separator
  if (offset !== null) fields += String(offset) + separator
  return fields
}
