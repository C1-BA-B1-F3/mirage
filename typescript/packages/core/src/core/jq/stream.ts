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

import { AsyncLineIterator } from '../../io/async_line_iterator.ts'
import { errorReport, formatOne } from './format.ts'
import { valueEnd } from './position.ts'
import { RS, type JqOptions } from './types.ts'

const DEC = new TextDecoder('utf-8', { fatal: false })
const WHITESPACE = /\s/
const NEWLINE = 0x0a

function parseSafe(text: string): unknown {
  return JSON.parse(text) as unknown
}

function documentEnd(text: string, start: number): number {
  const opener = text[start]
  if (opener !== '{' && opener !== '[') {
    if (opener !== '"') {
      let i = start
      while (i < text.length) {
        const ch = text[i]
        if (ch === undefined || WHITESPACE.test(ch)) break
        i += 1
      }
      return i
    }
    let i = start + 1
    while (i < text.length) {
      const ch = text[i]
      if (ch === '\\') {
        i += 2
        continue
      }
      if (ch === '"') return i + 1
      i += 1
    }
    return text.length
  }
  let depth = 0
  let inStr = false
  let i = start
  while (i < text.length) {
    const ch = text[i]
    if (inStr) {
      if (ch === '\\') i += 1
      else if (ch === '"') inStr = false
      i += 1
      continue
    }
    if (ch === '"') inStr = true
    else if (ch === '{' || ch === '[') depth += 1
    else if (ch === '}' || ch === ']') {
      depth -= 1
      if (depth === 0) return i + 1
    }
    i += 1
  }
  return text.length
}

/**
 * Parse a whitespace-separated stream of JSON values, and say where jq's
 * parser holds each one whole (see valueEnd).
 *
 * Returns every decoded document, in order, and the index into `text`
 * each one is whole at. Empty input holds no documents at all, which is
 * why jq prints nothing and exits 0 for an empty file.
 */
export function parseJsonText(text: string): [unknown[], number[]] {
  const stripped = text.trim()
  if (stripped === '') return [[], []]
  const lead = text.length - text.trimStart().length
  try {
    return [[parseSafe(stripped)], [valueEnd(text, lead + stripped.length)]]
  } catch (singleDocError) {
    const docs: unknown[] = []
    const ends: number[] = []
    let idx = 0
    while (idx < stripped.length) {
      const end = documentEnd(stripped, idx)
      if (end <= idx) throw singleDocError
      try {
        docs.push(parseSafe(stripped.slice(idx, end)))
      } catch {
        // Not a value stream either, so the input is simply invalid.
        // Re-throw the whole-document error: it names the real problem.
        throw singleDocError
      }
      ends.push(valueEnd(text, lead + end))
      idx = end
      while (idx < stripped.length) {
        const ch = stripped[idx]
        if (ch === undefined || !WHITESPACE.test(ch)) break
        idx += 1
      }
    }
    return [docs, ends]
  }
}

/** Parse a whitespace-separated stream of JSON values (see parseJsonText). */
export function parseJsonDocs(raw: Uint8Array): unknown[] {
  return parseJsonText(DEC.decode(raw))[0]
}

export function parseJsonAuto(raw: Uint8Array): unknown {
  const docs = parseJsonDocs(raw)
  if (docs.length === 0) throw new Error('jq: empty input')
  return docs.length === 1 ? docs[0] : docs
}

/**
 * Parse an RFC 7464 JSON text sequence (`--seq`), and say where jq's
 * parser holds each value whole.
 *
 * Every value is introduced by RS, so anything before the first one is
 * text the sequence never claimed. jq reports that as an ignored parse
 * error and prints nothing for it; mirage drops it just as silently,
 * which is the one divergence here.
 */
export function parseSeqText(text: string): [unknown[], number[]] {
  const docs: unknown[] = []
  const ends: number[] = []
  let offset = 0
  text.split(RS).forEach((part, i) => {
    const start = offset
    offset += part.length + 1
    if (i === 0 || part.trim() === '') return
    docs.push(parseSafe(part))
    ends.push(valueEnd(text, start + part.trimEnd().length))
  })
  return [docs, ends]
}

/** Parse an RFC 7464 JSON text sequence (see parseSeqText). */
export function parseSeqDocs(raw: Uint8Array): unknown[] {
  return parseSeqText(DEC.decode(raw))[0]
}

/**
 * Split one input into the strings `jq -R` reads it as, and say where
 * jq's reader holds each one: at its newline, or at the end of the input
 * for a last line that has none.
 *
 * jq breaks on newlines only (never on the other separators a Unicode
 * line splitter honors) and a trailing newline ends the last line rather
 * than starting an empty one.
 */
export function splitRawText(text: string): [string[], number[]] {
  if (text === '') return [[], []]
  const lines = text.split('\n')
  const ends: number[] = []
  let at = -1
  for (const line of lines) {
    at += line.length + 1
    ends.push(at)
  }
  if (lines[lines.length - 1] === '') {
    lines.pop()
    ends.pop()
  } else {
    ends[ends.length - 1] = text.length
  }
  return [lines, ends]
}

/** Split one input into the strings `jq -R` reads it as (see splitRawText). */
export function splitRawLines(raw: Uint8Array): string[] {
  return splitRawText(DEC.decode(raw))[0]
}

export function isJsonlPath(path: string): boolean {
  return path.endsWith('.jsonl') || path.endsWith('.ndjson')
}

export function isStreamableJsonlExpr(expression: string): boolean {
  return expression.trim().startsWith('.[]')
}

/**
 * Evaluate a per-element program over a JSONL file, line by line.
 *
 * Only output options reach here, since the caller keeps this path off
 * for anything that changes input assembly. A stream of outputs has no
 * room to report an error and go on, so the first error no `try` catches
 * ends the command, in jq's own words; `name` is the file as the command
 * line named it.
 */
export async function* evalJsonlStream(
  source: AsyncIterable<Uint8Array>,
  expression: string,
  opts: JqOptions,
  name: string,
): AsyncIterable<Uint8Array> {
  const { argsObject, jqRun, referencesArgs } = await import('./eval.ts')
  const expr = expression.trim()
  let perItem: string
  if (expr === '.[]') perItem = '.'
  else if (expr.startsWith('.[] | ')) perItem = expr.slice(6)
  else if (expr.startsWith('.[].')) perItem = expr.slice(3)
  else perItem = expr

  const argsValue = referencesArgs(perItem) ? argsObject(opts) : null
  const lines = new AsyncLineIterator(source)
  let newlines = 0
  for (;;) {
    const [lineBytes, found] = await lines.readUntil(NEWLINE)
    if (!found && lineBytes.byteLength === 0) return
    if (found) newlines += 1
    const text = DEC.decode(lineBytes).trim()
    if (text === '') continue
    const run = await jqRun(JSON.parse(text) as unknown, perItem, opts.namedArgs, null, argsValue)
    for (const value of run.outputs) yield formatOne(value, opts)
    if (run.stop?.kind === 'error') {
      throw new Error(errorReport(`${name}:${String(newlines)}`, run.stop).replace(/\n$/, ''))
    }
  }
}
