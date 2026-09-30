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

import { formatWcLines, type WcRow } from './generic/wc.ts'
import { rstripNewlines } from '../../utils/text.ts'
import { concat } from '../../io/cachable_iterator.ts'

export type AggregateResult = [path: string, data: Uint8Array]

export function concatAggregate(results: AggregateResult[]): Uint8Array {
  const chunks = results.map(([, data]) => data)
  return concat(chunks)
}

export function headerAggregate(results: AggregateResult[]): Uint8Array {
  const enc = new TextEncoder()
  const chunks: Uint8Array[] = []
  for (let i = 0; i < results.length; i++) {
    const entry = results[i]
    if (entry === undefined) continue
    const [path, data] = entry
    if (results.length > 1) {
      let header = `==> ${path} <==\n`
      if (i > 0) header = '\n' + header
      chunks.push(enc.encode(header))
    }
    chunks.push(data)
  }
  return concat(chunks)
}

export function prefixAggregate(results: AggregateResult[]): Uint8Array {
  const enc = new TextEncoder()
  const dec = new TextDecoder()
  const lines: string[] = []
  for (const [path, data] of results) {
    if (data.byteLength === 0) continue
    const text = rstripNewlines(dec.decode(data))
    for (const line of text.split('\n')) {
      lines.push(results.length > 1 ? `${path}:${line}` : line)
    }
  }
  if (lines.length === 0) return new Uint8Array(0)
  return enc.encode(lines.join('\n') + '\n')
}

export function wcAggregate(results: AggregateResult[]): Uint8Array {
  const enc = new TextEncoder()
  const dec = new TextDecoder()
  const rows: WcRow[] = []
  let totals: number[] = []
  for (const [path, data] of results) {
    const text = dec.decode(data).trim()
    if (text === '') continue
    const counts: number[] = []
    for (const token of text.split(/\s+/)) {
      if (!/^\d+$/.test(token)) break
      counts.push(Number.parseInt(token, 10))
    }
    if (counts.length === 0) continue
    rows.push({ values: counts, label: path })
    if (totals.length === 0) totals = new Array<number>(counts.length).fill(0)
    for (let idx = 0; idx < counts.length; idx++) {
      totals[idx] = (totals[idx] ?? 0) + (counts[idx] ?? 0)
    }
  }
  if (results.length > 1 && totals.length > 0) {
    rows.push({ values: totals, label: 'total' })
  }
  if (rows.length === 0) return new Uint8Array(0)
  return enc.encode(formatWcLines(rows).join('\n') + '\n')
}
