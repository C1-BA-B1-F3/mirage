import { getOpcodes } from '../../../builtin/diff_format.ts'
import { DiffOpTag } from '../../../builtin/diff_types.ts'
import { FUNCNAME_START, GIT_SPACE } from './constants.ts'

// Git 2.50.1 underflows the result count for -U0 combined deletions.
// Keep the valid zero-length range instead of its unsigned-size overflow.
const CONTEXT = 3
const COMMENT_BYTES = 40
const ENC = new TextEncoder()
const DEC = new TextDecoder()

type Lost = [string, number][]

/**
 * The hunks of a combined diff, as git's combine-diff.c selects them.
 *
 * Row `k` is result line `k`, carrying the parent lines deleted just before
 * it; row `result.length` carries the deletions at the end. `added[k]` has
 * bit `p` set when parent `p` lacks result line `k`, and each lost line
 * records the parents that had it.
 *
 * @param parents - each parent's lines, newlines kept.
 * @param result - the merge result's lines, newlines kept.
 * @param dense - `--cc`, which drops a hunk whose every change comes from
 *   the same proper subset of the parents.
 */
export function combinedLines(
  parents: string[][],
  result: string[],
  dense: boolean,
  context = CONTEXT,
): string[] {
  const size = result.length
  const added = Array<number>(size + 1).fill(0)
  const lost: Lost[] = Array.from({ length: size + 1 }, () => [])
  parents.forEach((old, parent) => {
    const bit = 1 << parent
    for (const [tag, i, end, j, stop] of getOpcodes(old, result)) {
      if (tag === DiffOpTag.EQUAL) continue
      for (let at = j; at < stop; at++) added[at] = (added[at] ?? 0) | bit
      const bucket = lost[j] ?? []
      for (const line of old.slice(i, end)) {
        const found = bucket.find(([text, owners]) => text === line && !(owners & bit))
        if (found) found[1] |= bit
        else bucket.push([line, bit])
      }
    }
  })
  const marked = added.map((bits, at) => bits !== 0 || (lost[at]?.length ?? 0) > 0)
  if (dense) dropOneSided(added, lost, marked, (1 << parents.length) - 1, context)
  const hidden = giveContext(added, marked, context)
  return dump(result, added, lost, marked, hidden, parents.length)
}

function tail(added: number[], begin: number, at: number): number {
  return begin + 1 <= at && !added[at - 1] ? at - 1 : at
}

function find(marked: boolean[], at: number, want: boolean): number {
  while (at < marked.length && marked[at] !== want) at++
  return at
}

function dropOneSided(
  added: number[],
  lost: Lost[],
  marked: boolean[],
  everyone: number,
  context: number,
): void {
  const size = marked.length - 1
  let at = 0
  for (;;) {
    at = find(marked, at, true)
    if (at > size) return
    const begin = at
    let end = at + 1
    while (end <= size) {
      if (!marked[end]) {
        const reach = Math.min(tail(added, begin, end) + context, size + 1)
        let ahead = -1
        for (let k = reach - 1; k >= end; k--)
          if (marked[k]) {
            ahead = k
            break
          }
        if (ahead < 0) break
        end = ahead
      }
      end++
    }
    const sides = new Set<number>()
    for (let k = begin; k < end; k++) {
      if (added[k]) sides.add(added[k] ?? 0)
      for (const [, owners] of lost[k] ?? []) sides.add(owners)
    }
    if (sides.size === 1 && !sides.has(everyone)) marked.fill(false, begin, end)
    at = end
  }
}

function giveContext(added: number[], marked: boolean[], context: number): Set<number> {
  const size = marked.length - 1
  const hidden = new Set<number>()
  let at = find(marked, 0, true)
  while (at <= size) {
    for (let k = Math.max(0, at - context); k < at; k++) {
      if (!marked[k]) hidden.add(k)
      marked[k] = true
    }
    let gap: number, ahead: number
    for (;;) {
      gap = find(marked, at, false)
      if (gap > size) return hidden
      ahead = find(marked, gap, true)
      gap = tail(added, at, gap)
      if (ahead >= gap + context) break
      marked.fill(true, gap, ahead)
      at = ahead
    }
    at = ahead
    marked.fill(true, gap, Math.min(gap + context, size + 1))
  }
  return hidden
}

function dump(
  result: string[],
  added: number[],
  lost: Lost[],
  marked: boolean[],
  hidden: Set<number>,
  count: number,
): string[] {
  const size = result.length
  const parents = Array.from({ length: count }, (_, p) => p)
  const starts: number[][] = [Array<number>(count).fill(1)]
  for (let k = 0; k <= size; k++) {
    const row = [...(starts.at(-1) ?? [])]
    for (const p of parents) {
      row[p] = (row[p] ?? 0) + (lost[k] ?? []).filter(([, owners]) => (owners >> p) & 1).length
      if (k < size && !(((added[k] ?? 0) >> p) & 1)) row[p] = (row[p] ?? 0) + 1
    }
    starts.push(row)
  }
  const marker = '@'.repeat(count + 1)
  const output: string[] = []
  let at = 0
  for (;;) {
    let comment: string | null = null
    while (at <= size && !marked[at]) {
      const line = result[at]
      if (line !== undefined && FUNCNAME_START.test(line)) comment = line
      at++
    }
    if (at > size) return output
    const end = find(marked, at + 1, false)
    const from = starts[at] ?? [],
      to = starts[end] ?? []
    const ranges = parents
      .map((p) => `-${String(from[p] ?? 0)},${String((to[p] ?? 0) - (from[p] ?? 0))}`)
      .join(' ')
    const rows = end - at - Number(end > size)
    output.push(
      `${marker} ${ranges} +${String(at + 1)},${String(rows)} ${marker}${funcname(comment)}\n`,
    )
    for (let k = at; k < end; k++) {
      if (!hidden.has(k))
        for (const [text, owners] of lost[k] ?? [])
          output.push(parents.map((p) => ((owners >> p) & 1 ? '-' : ' ')).join('') + eol(text))
      if (k < size)
        output.push(
          parents.map((p) => (((added[k] ?? 0) >> p) & 1 ? '+' : ' ')).join('') +
            eol(result[k] ?? ''),
        )
    }
    at = end
  }
}

/**
 * The hunk header's trailing context, cut the way git cuts it: the first
 * 40 bytes up to a newline, stopping BEFORE the last non-blank byte, so the
 * context always loses its final byte.
 */
function funcname(line: string | null): string {
  if (line === null) return ''
  let head = ENC.encode(line).subarray(0, COMMENT_BYTES)
  const stop = head.findIndex((c) => c === 0x0a || c === 0x00)
  if (stop >= 0) head = head.subarray(0, stop)
  let end = 0
  head.forEach((c, i) => {
    if (!GIT_SPACE.has(c)) end = i
  })
  return end ? ' ' + DEC.decode(head.subarray(0, end)) : ''
}

function eol(line: string): string {
  return line.endsWith('\n') ? line : line + '\n'
}
