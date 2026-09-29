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

const ENC = new TextEncoder()

export function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

// Every backend renders a .json leaf through here, so read() and the
// readdir-time sizing produce the same bytes for the same payload and the
// advertised size is exact by construction.
export function jsonBytes(value: unknown): Uint8Array {
  return ENC.encode(jsonText(value))
}

export function compactJsonText(value: unknown): string {
  return JSON.stringify(value)
}

export function compactJsonBytes(value: unknown): Uint8Array {
  return ENC.encode(compactJsonText(value))
}

/**
 * Spell a number the way ECMAScript's `Number::toString` does, which is what
 * `JSON.stringify` writes for a finite one. `String()` is the spec here; the
 * python twin reproduces its layout from `repr`, whose digits agree and whose
 * exponent thresholds and padding do not. A non-finite value has no JSON
 * spelling and renders `null`, as `JSON.stringify` does.
 */
export function numberText(value: number): string {
  return Number.isFinite(value) ? String(value) : 'null'
}

/**
 * Spell a payload value as text, as compact JSON in both languages.
 *
 * A string is itself; anything else renders as compact JSON, so a boolean
 * spells `true` rather than Python's `True`, a number lays out as
 * `numberText` says, and an object or array spells as one JSON literal rather
 * than `[object Object]`, its numbers included. Path labels and group values
 * are built from this, so one collection grows one tree.
 */
export function valueText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'bigint') return value.toString()
  if (typeof value === 'number') return numberText(value)
  return compactJsonText(value)
}

// JSON.stringify supplies ECMAScript number spelling, including nested cells.
// An empty row list renders as empty bytes rather than a lone newline, so an
// empty .jsonl leaf sizes and reads as a zero-byte file.
export function jsonlBytes(rows: readonly unknown[]): Uint8Array {
  if (rows.length === 0) return new Uint8Array()
  return ENC.encode(rows.map((row) => compactJsonText(row)).join('\n') + '\n')
}

// A comment feed arrives in whatever order the API paginated it, and a file
// that reads the same twice needs a stable order. `created_at` is the one
// field every comment normalizer emits, and a row missing it sorts first
// rather than throwing.
export function jsonlBytesByCreatedAt(rows: readonly { created_at?: string | null }[]): Uint8Array {
  const ordered = [...rows].sort((a, b) => {
    const ka = a.created_at ?? ''
    const kb = b.created_at ?? ''
    if (ka < kb) return -1
    if (ka > kb) return 1
    return 0
  })
  return jsonlBytes(ordered)
}
