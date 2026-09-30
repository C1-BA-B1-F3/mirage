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

import type { JsonValue } from '../kit/typescript/index.ts'
import { blobSha } from './wire.ts'
import type { Tree } from './store.ts'

// git's defaults: three lines of context, a blob is binary when its first
// 8000 bytes hold a NUL, and a hunk header carries at most 80 bytes of the
// line it is found under.
const CONTEXT = 3
const BINARY_PROBE = 8000
const FUNC_LINE_BYTES = 80

// A short object id, as a repository this small abbreviates one. Measured
// against GitHub (2026-09-29): octocat/git-consortium's diffs print seven hex
// digits; a repository with far more objects prints more.
const ABBREV = 7
const NO_BLOB = '0'.repeat(ABBREV)

type ChangeStatus = 'added' | 'removed' | 'modified' | 'renamed'

/**
 * One path that differs between two trees, as git reports it. Its hunks hold
 * the file's bytes, one character each.
 */
export interface FileChange {
  filename: string
  previous: string | null
  status: ChangeStatus
  before: string
  after: string
  binary: boolean
  additions: number
  deletions: number
  hunks: string[]
}

interface Op {
  kind: ' ' | '-' | '+'
  text: string
}

// Each line keeps its terminator, so a last line with no newline differs from
// the same text with one, which is how git compares them. A line is its bytes,
// one character each, because git diffs bytes: decoding as UTF-8 would
// replace any other encoding's bytes before the diff saw them.
function linesOf(data: Buffer): string[] {
  const text = data.toString('latin1')
  const out: string[] = []
  let at = 0
  while (at < text.length) {
    const nl = text.indexOf('\n', at)
    if (nl < 0) {
      out.push(text.slice(at))
      break
    }
    out.push(text.slice(at, nl + 1))
    at = nl + 1
  }
  return out
}

function isBinary(data: Buffer): boolean {
  return data.subarray(0, BINARY_PROBE).includes(0)
}

// xdiff's constants, as git ships them.
const SNAKE_CNT = 20
const HEUR_MIN_COST = 256
const MAX_COST_MIN = 256
const K_HEUR = 4
const LINE_MAX = Number.MAX_SAFE_INTEGER
const MAX_EQLIMIT = 1024
const SIMSCAN_WINDOW = 100
const KPDIS_RUN = 4

function bogosqrt(n: number): number {
  let i = 1
  for (let rest = n; rest > 0; rest = Math.floor(rest / 4)) i *= 2
  return i
}

interface Split {
  i1: number
  i2: number
  minLo: boolean
  minHi: boolean
}

interface Env {
  kf: number[]
  kb: number[]
  o: number
  mxcost: number
}

// xdl_split: Myers' middle snake over the box (off1, off2)..(lim1, lim2),
// walked from both corners at once, with xdiff's cut-offs for a costly box.
function split(
  ha1: number[],
  off1: number,
  lim1: number,
  ha2: number[],
  off2: number,
  lim2: number,
  needMin: boolean,
  env: Env,
): Split {
  const { kf, kb, o } = env
  const at = (k: number[], d: number): number => k[d + o] ?? 0
  const dmin = off1 - lim2
  const dmax = lim1 - off2
  const fmid = off1 - off2
  const bmid = lim1 - lim2
  const odd = ((fmid - bmid) & 1) !== 0
  let fmin = fmid
  let fmax = fmid
  let bmin = bmid
  let bmax = bmid
  kf[fmid + o] = off1
  kb[bmid + o] = lim1
  for (let ec = 1; ; ec += 1) {
    let gotSnake = false
    if (fmin > dmin) kf[--fmin - 1 + o] = -1
    else fmin += 1
    if (fmax < dmax) kf[++fmax + 1 + o] = -1
    else fmax -= 1
    for (let d = fmax; d >= fmin; d -= 2) {
      let i1 = at(kf, d - 1) >= at(kf, d + 1) ? at(kf, d - 1) + 1 : at(kf, d + 1)
      const prev1 = i1
      let i2 = i1 - d
      while (i1 < lim1 && i2 < lim2 && ha1[i1] === ha2[i2]) {
        i1 += 1
        i2 += 1
      }
      if (i1 - prev1 > SNAKE_CNT) gotSnake = true
      kf[d + o] = i1
      if (odd && bmin <= d && d <= bmax && at(kb, d) <= i1) {
        return { i1, i2, minLo: true, minHi: true }
      }
    }
    if (bmin > dmin) kb[--bmin - 1 + o] = LINE_MAX
    else bmin += 1
    if (bmax < dmax) kb[++bmax + 1 + o] = LINE_MAX
    else bmax -= 1
    for (let d = bmax; d >= bmin; d -= 2) {
      let i1 = at(kb, d - 1) < at(kb, d + 1) ? at(kb, d - 1) : at(kb, d + 1) - 1
      const prev1 = i1
      let i2 = i1 - d
      while (i1 > off1 && i2 > off2 && ha1[i1 - 1] === ha2[i2 - 1]) {
        i1 -= 1
        i2 -= 1
      }
      if (prev1 - i1 > SNAKE_CNT) gotSnake = true
      kb[d + o] = i1
      if (!odd && fmin <= d && d <= fmax && i1 <= at(kf, d)) {
        return { i1, i2, minLo: true, minHi: true }
      }
    }
    if (needMin) continue
    if (gotSnake && ec > HEUR_MIN_COST) {
      let best = 0
      let found: Split | null = null
      for (let d = fmax; d >= fmin; d -= 2) {
        const dd = d > fmid ? d - fmid : fmid - d
        const i1 = at(kf, d)
        const i2 = i1 - d
        const v = i1 - off1 + (i2 - off2) - dd
        if (
          v > K_HEUR * ec &&
          v > best &&
          off1 + SNAKE_CNT <= i1 &&
          i1 < lim1 &&
          off2 + SNAKE_CNT <= i2 &&
          i2 < lim2
        ) {
          for (let k = 1; ha1[i1 - k] === ha2[i2 - k]; k += 1) {
            if (k === SNAKE_CNT) {
              best = v
              found = { i1, i2, minLo: true, minHi: false }
              break
            }
          }
        }
      }
      if (found !== null) return found
      best = 0
      for (let d = bmax; d >= bmin; d -= 2) {
        const dd = d > bmid ? d - bmid : bmid - d
        const i1 = at(kb, d)
        const i2 = i1 - d
        const v = lim1 - i1 + (lim2 - i2) - dd
        if (
          v > K_HEUR * ec &&
          v > best &&
          off1 < i1 &&
          i1 <= lim1 - SNAKE_CNT &&
          off2 < i2 &&
          i2 <= lim2 - SNAKE_CNT
        ) {
          for (let k = 0; ha1[i1 + k] === ha2[i2 + k]; k += 1) {
            if (k === SNAKE_CNT - 1) {
              best = v
              found = { i1, i2, minLo: false, minHi: true }
              break
            }
          }
        }
      }
      if (found !== null) return found
    }
    if (ec >= env.mxcost) {
      let fbest = -1
      let fbest1 = -1
      for (let d = fmax; d >= fmin; d -= 2) {
        let i1 = Math.min(at(kf, d), lim1)
        let i2 = i1 - d
        if (lim2 < i2) {
          i1 = lim2 + d
          i2 = lim2
        }
        if (fbest < i1 + i2) {
          fbest = i1 + i2
          fbest1 = i1
        }
      }
      let bbest = LINE_MAX
      let bbest1 = LINE_MAX
      for (let d = bmax; d >= bmin; d -= 2) {
        let i1 = Math.max(off1, at(kb, d))
        let i2 = i1 - d
        if (i2 < off2) {
          i1 = off2 + d
          i2 = off2
        }
        if (i1 + i2 < bbest) {
          bbest = i1 + i2
          bbest1 = i1
        }
      }
      if (lim1 + lim2 - bbest < fbest - (off1 + off2)) {
        return { i1: fbest1, i2: fbest - fbest1, minLo: true, minHi: false }
      }
      return { i1: bbest1, i2: bbest - bbest1, minLo: false, minHi: true }
    }
  }
}

interface Reduced {
  ha: number[]
  rindex: number[]
  side: Side
}

// xdl_recs_cmp: shrink the box past its matching ends, mark whatever is left
// when one side runs out, and otherwise split it and recurse into both halves.
function recsCmp(
  one: Reduced,
  from1: number,
  to1: number,
  two: Reduced,
  from2: number,
  to2: number,
  needMin: boolean,
  env: Env,
): void {
  let off1 = from1
  let lim1 = to1
  let off2 = from2
  let lim2 = to2
  while (off1 < lim1 && off2 < lim2 && one.ha[off1] === two.ha[off2]) {
    off1 += 1
    off2 += 1
  }
  while (off1 < lim1 && off2 < lim2 && one.ha[lim1 - 1] === two.ha[lim2 - 1]) {
    lim1 -= 1
    lim2 -= 1
  }
  if (off1 === lim1) {
    for (; off2 < lim2; off2 += 1) mark(two.side, two.rindex[off2] ?? 0, true)
  } else if (off2 === lim2) {
    for (; off1 < lim1; off1 += 1) mark(one.side, one.rindex[off1] ?? 0, true)
  } else {
    const spl = split(one.ha, off1, lim1, two.ha, off2, lim2, needMin, env)
    recsCmp(one, off1, spl.i1, two, off2, spl.i2, spl.minLo, env)
    recsCmp(one, spl.i1, lim1, two, spl.i2, lim2, spl.minHi, env)
  }
}

// xdl_clean_mmatch: a line with many matches is left out of the search only
// in the middle of a run of lines with none.
function cleanMmatch(dis: Uint8Array, i: number, start: number, end: number): boolean {
  const s = i - start > SIMSCAN_WINDOW ? i - SIMSCAN_WINDOW : start
  const e = end - i > SIMSCAN_WINDOW ? i + SIMSCAN_WINDOW : end
  let rdis0 = 0
  let rpdis0 = 1
  for (let r = 1; i - r >= s; r += 1) {
    const v = dis[i - r]
    if (v === 0) rdis0 += 1
    else if (v === 2) rpdis0 += 1
    else break
  }
  if (rdis0 === 0) return false
  let rdis1 = 0
  let rpdis1 = 1
  for (let r = 1; i + r <= e; r += 1) {
    const v = dis[i + r]
    if (v === 0) rdis1 += 1
    else if (v === 2) rpdis1 += 1
    else break
  }
  if (rdis1 === 0) return false
  rdis1 += rdis0
  rpdis1 += rpdis0
  return rpdis1 * KPDIS_RUN < rpdis1 + rdis1
}

// xdl_prepare_env and xdl_do_diff: every line is classed by its content, the
// matching ends are trimmed, a line the other side never has is changed
// outright, and Myers' search runs over the rest. The result is which lines
// of each side the diff changed.
function lineOps(a: string[], b: string[]): Op[] {
  const classes = new Map<string, number>()
  const classOf = (line: string): number => {
    const known = classes.get(line)
    if (known !== undefined) return known
    classes.set(line, classes.size)
    return classes.size - 1
  }
  const ha1 = a.map(classOf)
  const ha2 = b.map(classOf)
  const count = (ha: number[]): Map<number, number> => {
    const out = new Map<number, number>()
    for (const h of ha) out.set(h, (out.get(h) ?? 0) + 1)
    return out
  }
  const in1 = count(ha1)
  const in2 = count(ha2)
  const old: Side = { recs: a, chg: new Uint8Array(a.length + 2) }
  const neu: Side = { recs: b, chg: new Uint8Array(b.length + 2) }
  const lim = Math.min(a.length, b.length)
  let dstart = 0
  while (dstart < lim && ha1[dstart] === ha2[dstart]) dstart += 1
  let tail = 0
  while (tail < lim - dstart && ha1[a.length - 1 - tail] === ha2[b.length - 1 - tail]) tail += 1
  const reduce = (ha: number[], side: Side, others: Map<number, number>): Reduced => {
    const dend = ha.length - tail - 1
    const mlim = Math.min(bogosqrt(ha.length), MAX_EQLIMIT)
    const dis = new Uint8Array(ha.length + 1)
    for (let i = dstart; i <= dend; i += 1) {
      const nm = others.get(ha[i] ?? -1) ?? 0
      dis[i] = nm === 0 ? 0 : nm >= mlim ? 2 : 1
    }
    const out: Reduced = { ha: [], rindex: [], side }
    for (let i = dstart; i <= dend; i += 1) {
      if (dis[i] === 1 || (dis[i] === 2 && !cleanMmatch(dis, i, dstart, dend))) {
        out.rindex.push(i)
        out.ha.push(ha[i] ?? -1)
      } else {
        mark(side, i, true)
      }
    }
    return out
  }
  const one = reduce(ha1, old, in2)
  const two = reduce(ha2, neu, in1)
  const ndiags = one.ha.length + two.ha.length + 3
  const env: Env = {
    kf: new Array<number>(ndiags).fill(0),
    kb: new Array<number>(ndiags).fill(0),
    o: two.ha.length + 1,
    mxcost: Math.max(bogosqrt(ndiags), MAX_COST_MIN),
  }
  recsCmp(one, 0, one.ha.length, two, 0, two.ha.length, false, env)
  compact(old, neu)
  compact(neu, old)
  const out: Op[] = []
  let i = 0
  let j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && changed(old, i)) out.push({ kind: '-', text: a[i++] ?? '' })
    else if (j < b.length && changed(neu, j)) out.push({ kind: '+', text: b[j++] ?? '' })
    else {
      out.push({ kind: ' ', text: a[i] ?? '' })
      i += 1
      j += 1
    }
  }
  return out
}

// One side of a diff as xdiff compacts it: its lines, and which of them the
// diff changed, kept one slot past either end so the edges read unchanged.
interface Side {
  recs: string[]
  chg: Uint8Array
}

interface Group {
  start: number
  end: number
}

const changed = (side: Side, line: number): boolean => side.chg[line + 1] === 1

function mark(side: Side, line: number, on: boolean): void {
  side.chg[line + 1] = on ? 1 : 0
}

function groupFirst(side: Side): Group {
  const g = { start: 0, end: 0 }
  while (changed(side, g.end)) g.end += 1
  return g
}

function groupNext(side: Side, g: Group): boolean {
  if (g.end === side.recs.length) return false
  g.start = g.end + 1
  g.end = g.start
  while (changed(side, g.end)) g.end += 1
  return true
}

function groupPrevious(side: Side, g: Group): boolean {
  if (g.start === 0) return false
  g.end = g.start - 1
  g.start = g.end
  while (changed(side, g.start - 1)) g.start -= 1
  return true
}

function slideDown(side: Side, g: Group): boolean {
  if (g.end >= side.recs.length || side.recs[g.start] !== side.recs[g.end]) return false
  mark(side, g.start, false)
  mark(side, g.end, true)
  g.start += 1
  g.end += 1
  while (changed(side, g.end)) g.end += 1
  return true
}

function slideUp(side: Side, g: Group): boolean {
  if (g.start === 0 || side.recs[g.start - 1] !== side.recs[g.end - 1]) return false
  g.start -= 1
  g.end -= 1
  mark(side, g.start, true)
  mark(side, g.end, false)
  while (changed(side, g.start - 1)) g.start -= 1
  return true
}

// xdiff's indent heuristic, its constants as git ships them: where a block of
// added or removed lines could sit at several places, the place whose two
// edges fall best against the surrounding indentation and blank lines wins.
const MAX_INDENT = 200
const MAX_BLANKS = 20
const INDENT_HEURISTIC_MAX_SLIDING = 100
const INDENT_WEIGHT = 60

function indentOf(line: string | undefined): number {
  let indent = 0
  for (const c of line ?? '') {
    if (c === ' ') indent += 1
    else if (c === '\t') indent += 8 - (indent % 8)
    else if (!'\n\v\f\r'.includes(c)) return indent
    if (indent >= MAX_INDENT) return MAX_INDENT
  }
  return -1
}

interface Score {
  effectiveIndent: number
  penalty: number
}

function scoreSplit(recs: string[], split: number, score: Score): void {
  const endOfFile = split >= recs.length
  const indent = endOfFile ? -1 : indentOf(recs[split])
  let preBlank = 0
  let preIndent = -1
  for (let i = split - 1; i >= 0; i -= 1) {
    preIndent = indentOf(recs[i])
    if (preIndent !== -1) break
    preBlank += 1
    if (preBlank === MAX_BLANKS) {
      preIndent = 0
      break
    }
  }
  let postBlank = 0
  let postIndent = -1
  for (let i = split + 1; i < recs.length; i += 1) {
    postIndent = indentOf(recs[i])
    if (postIndent !== -1) break
    postBlank += 1
    if (postBlank === MAX_BLANKS) {
      postIndent = 0
      break
    }
  }
  if (preIndent === -1 && preBlank === 0) score.penalty += 1
  if (endOfFile) score.penalty += 21
  const blankAfter = indent === -1 ? 1 + postBlank : 0
  const totalBlank = preBlank + blankAfter
  score.penalty += -30 * totalBlank + 6 * blankAfter
  const effective = indent !== -1 ? indent : postIndent
  const anyBlanks = totalBlank !== 0
  score.effectiveIndent += effective
  if (effective === -1 || preIndent === -1 || effective === preIndent) return
  if (effective > preIndent) score.penalty += anyBlanks ? 10 : -4
  else if (postIndent !== -1 && postIndent > effective) score.penalty += anyBlanks ? 17 : 24
  else score.penalty += anyBlanks ? 17 : 23
}

function scoreCompare(a: Score, b: Score): number {
  const indents =
    Number(a.effectiveIndent > b.effectiveIndent) - Number(a.effectiveIndent < b.effectiveIndent)
  return INDENT_WEIGHT * indents + (a.penalty - b.penalty)
}

// xdl_change_compact: each block of changed lines slides up as far as it can
// and then down as far as it can, merging with any block it meets, and ends
// either lined up with the last change on the other side it can meet or
// where the indent heuristic puts it. That is how git picks one diff among
// the minimal ones, and the reason its output is the same on every machine.
function compact(side: Side, other: Side): void {
  const g = groupFirst(side)
  const go = groupFirst(other)
  for (;;) {
    if (g.end !== g.start) {
      let size: number
      let earliestEnd: number
      let endMatchingOther: number
      do {
        size = g.end - g.start
        endMatchingOther = -1
        while (slideUp(side, g)) groupPrevious(other, go)
        earliestEnd = g.end
        if (go.end > go.start) endMatchingOther = g.end
        while (slideDown(side, g)) {
          groupNext(other, go)
          if (go.end > go.start) endMatchingOther = g.end
        }
      } while (size !== g.end - g.start)
      if (g.end === earliestEnd) {
        // nothing could move
      } else if (endMatchingOther !== -1) {
        while (go.end === go.start) {
          slideUp(side, g)
          groupPrevious(other, go)
        }
      } else {
        let shift = Math.max(earliestEnd, g.end - size - 1, g.end - INDENT_HEURISTIC_MAX_SLIDING)
        let best = -1
        let bestScore: Score = { effectiveIndent: 0, penalty: 0 }
        for (; shift <= g.end; shift += 1) {
          const score = { effectiveIndent: 0, penalty: 0 }
          scoreSplit(side.recs, shift, score)
          scoreSplit(side.recs, shift - size, score)
          if (best === -1 || scoreCompare(score, bestScore) <= 0) {
            bestScore = score
            best = shift
          }
        }
        while (g.end > best) {
          slideUp(side, g)
          groupPrevious(other, go)
        }
      }
    }
    if (!groupNext(side, g)) break
    groupNext(other, go)
  }
}

// git's default funcname: the nearest line above the hunk, in the old file,
// that starts with a letter, `_` or `$`, cut to 80 bytes and stripped of
// trailing whitespace. A hunk that finds none keeps the one before it.
function funcLine(line: string): string | null {
  if (!/^[A-Za-z_$]/.test(line)) return null
  return line.slice(0, FUNC_LINE_BYTES).replace(/[ \t\n\v\f\r]+$/, '')
}

function hunkRange(start: number, count: number): string {
  const shown = count === 0 ? start : start + 1
  return count === 1 ? String(shown) : `${String(shown)},${String(count)}`
}

// The hunks of one file: changes closer than twice the context apart share a
// hunk, as xdiff joins them, and each line that ends without a newline is
// followed by git's marker for it.
function hunksOf(ops: Op[], before: string[]): string[] {
  const changed = ops.flatMap((op, i) => (op.kind === ' ' ? [] : [i]))
  const first = changed[0]
  if (first === undefined) return []
  const oldAt: number[] = []
  const newAt: number[] = []
  let o = 0
  let n = 0
  for (const op of ops) {
    oldAt.push(o)
    newAt.push(n)
    if (op.kind !== '+') o += 1
    if (op.kind !== '-') n += 1
  }
  const groups: Array<[number, number]> = []
  let start = first
  let end = first + 1
  for (const i of changed.slice(1)) {
    if (i - end <= 2 * CONTEXT) {
      end = i + 1
      continue
    }
    groups.push([start, end])
    start = i
    end = i + 1
  }
  groups.push([start, end])
  let func = ''
  let searched = -1
  return groups.map(([s, e]) => {
    const from = Math.max(0, s - CONTEXT)
    const to = Math.min(ops.length, e + CONTEXT)
    const slice = ops.slice(from, to)
    const oldStart = oldAt[from] ?? 0
    const newStart = newAt[from] ?? 0
    for (let l = oldStart - 1; l > searched && l >= 0; l -= 1) {
      const found = funcLine(before[l] ?? '')
      if (found !== null) {
        func = found
        break
      }
    }
    searched = oldStart - 1
    const oldCount = slice.filter((op) => op.kind !== '+').length
    const newCount = slice.filter((op) => op.kind !== '-').length
    const header = `@@ -${hunkRange(oldStart, oldCount)} +${hunkRange(newStart, newCount)} @@`
    const body = slice
      .map((op) => {
        const line = `${op.kind}${op.text}`
        return line.endsWith('\n') ? line : `${line}\n\\ No newline at end of file\n`
      })
      .join('')
    return `${header}${func === '' ? '' : ` ${func}`}\n${body}`
  })
}

function change(
  filename: string,
  previous: string | null,
  status: ChangeStatus,
  was: Buffer | undefined,
  now: Buffer | undefined,
): FileChange {
  const old = was ?? Buffer.alloc(0)
  const neu = now ?? Buffer.alloc(0)
  const binary = isBinary(old) || isBinary(neu)
  const before = linesOf(old)
  const ops = binary || status === 'renamed' ? [] : lineOps(before, linesOf(neu))
  return {
    filename,
    previous,
    status,
    before: was === undefined ? '' : blobSha(was),
    after: now === undefined ? '' : blobSha(now),
    binary,
    additions: ops.filter((op) => op.kind === '+').length,
    deletions: ops.filter((op) => op.kind === '-').length,
    hunks: hunksOf(ops, before),
  }
}

/**
 * Every path that differs between two trees, in path order. A removed path
 * whose exact bytes reappear under a path that was added is one rename, which
 * is the part of git's rename detection a byte comparison can answer. As in
 * git's exact pass, each added path takes the first unused removed path with
 * the same bytes, preferring one with the same file name.
 */
export function diffTrees(before: Tree, after: Tree): FileChange[] {
  const out: FileChange[] = []
  const removed = [...before.keys()].filter((p) => !after.has(p)).sort()
  const renamedFrom = new Set<string>()
  for (const path of [...after.keys()].sort()) {
    const now = after.get(path)
    const was = before.get(path)
    if (was !== undefined) {
      if (now !== undefined && !was.equals(now)) {
        out.push(change(path, null, 'modified', was, now))
      }
      continue
    }
    const name = (p: string): string => p.slice(p.lastIndexOf('/') + 1)
    const same = removed.filter(
      (old) => !renamedFrom.has(old) && now !== undefined && before.get(old)?.equals(now),
    )
    const source = same.find((old) => name(old) === name(path)) ?? same[0]
    if (source !== undefined) {
      renamedFrom.add(source)
      out.push(change(path, source, 'renamed', before.get(source), now))
    } else {
      out.push(change(path, null, 'added', undefined, now))
    }
  }
  for (const path of removed) {
    if (!renamedFrom.has(path)) out.push(change(path, null, 'removed', before.get(path), undefined))
  }
  return out.sort((a, b) => (a.filename < b.filename ? -1 : a.filename > b.filename ? 1 : 0))
}

const C_ESCAPES: Record<string, string> = {
  '\x07': '\\a',
  '\b': '\\b',
  '\t': '\\t',
  '\n': '\\n',
  '\v': '\\v',
  '\f': '\\f',
  '\r': '\\r',
  '"': '\\"',
  '\\': '\\\\',
}

// A path as git prints it in a diff: bare unless it holds a quote, a
// backslash, a control character or a byte past ASCII, and then C-quoted with
// each such byte in octal, the way `core.quotePath` leaves it by default.
function quoted(path: string): string {
  const bytes = Buffer.from(path)
  if (!bytes.some((b) => b < 0x20 || b >= 0x7f || b === 0x22 || b === 0x5c)) return path
  let out = ''
  for (const byte of bytes) {
    const ch = String.fromCharCode(byte)
    const escape = C_ESCAPES[ch]
    if (escape !== undefined) out += escape
    else if (byte < 0x20 || byte >= 0x7f) out += `\\${byte.toString(8).padStart(3, '0')}`
    else out += ch
  }
  return `"${out}"`
}

function short(sha: string): string {
  return sha === '' ? NO_BLOB : sha.slice(0, ABBREV)
}

// One file's section of `git diff`, headers and all, the body GitHub serves as
// `application/vnd.github.diff`.
function fileDiff(c: FileChange): string {
  const was = c.previous ?? c.filename
  const lines = [`diff --git ${quoted(`a/${was}`)} ${quoted(`b/${c.filename}`)}`]
  if (c.status === 'renamed') {
    lines.push(
      'similarity index 100%',
      `rename from ${quoted(was)}`,
      `rename to ${quoted(c.filename)}`,
    )
    return `${lines.join('\n')}\n`
  }
  if (c.status === 'added')
    lines.push('new file mode 100644', `index ${NO_BLOB}..${short(c.after)}`)
  else if (c.status === 'removed')
    lines.push('deleted file mode 100644', `index ${short(c.before)}..${NO_BLOB}`)
  else lines.push(`index ${short(c.before)}..${short(c.after)} 100644`)
  // git follows a name holding a space with a tab on these two lines, so a
  // patch tool can tell where the name ends.
  const tab = (name: string): string => (name.includes(' ') ? `${name}\t` : name)
  const from = c.status === 'added' ? '/dev/null' : tab(quoted(`a/${was}`))
  const to = c.status === 'removed' ? '/dev/null' : tab(quoted(`b/${c.filename}`))
  if (c.binary) {
    const plain = (side: string, name: string): string =>
      side === '/dev/null' ? side : quoted(name)
    lines.push(`Binary files ${plain(from, `a/${was}`)} and ${plain(to, `b/${c.filename}`)} differ`)
  } else if (c.hunks.length > 0) lines.push(`--- ${from}`, `+++ ${to}`)
  return `${lines.join('\n')}\n${c.hunks.join('')}`
}

/** The whole `git diff` of a set of changes, byte for byte. */
export function unifiedDiff(changes: FileChange[]): Buffer {
  return Buffer.from(changes.map(fileDiff).join(''), 'latin1')
}

/**
 * What GitHub's `patch` field holds: the hunks, without the last newline, as
 * text, since a JSON string can carry nothing else.
 */
function patchOf(c: FileChange): string | null {
  if (c.binary || c.hunks.length === 0) return null
  return Buffer.from(c.hunks.join('').replace(/\n$/, ''), 'latin1').toString('utf8')
}

/**
 * One line of a file's patch as a review comment addresses it: by its
 * `position`, counted from the first hunk header, which is 0, or by its line
 * number on the side that holds it. `header` is the position of the hunk
 * header above it.
 */
export interface PatchLine {
  text: string
  position: number
  kind: string
  old: number | null
  new: number | null
  header: number
}

export function patchLines(c: FileChange): PatchLine[] {
  const patch = patchOf(c)
  if (patch === null) return []
  const out: PatchLine[] = []
  let old = 0
  let neu = 0
  let header = 0
  for (const [position, text] of patch.split('\n').entries()) {
    const kind = text.charAt(0)
    const range = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text)
    if (range !== null) {
      old = Number(range[1])
      neu = Number(range[2])
      header = position
      out.push({ text, position, kind, old: null, new: null, header })
      continue
    }
    const onOld = kind === ' ' || kind === '-'
    const onNew = kind === ' ' || kind === '+'
    out.push({ text, position, kind, old: onOld ? old : null, new: onNew ? neu : null, header })
    if (onOld) old += 1
    if (onNew) neu += 1
  }
  return out
}

function urlPath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
}

/**
 * One changed file as the REST API lists it for a pull request, a comparison
 * or a commit. `before` and `after` are the commits either side of the
 * change: a removed file links to the side that still has it, as GitHub's
 * does, and every other file to the side that has it now.
 */
export function changeJson(
  fullName: string,
  c: FileChange,
  before: string,
  after: string,
): JsonValue {
  const ref = c.status === 'removed' ? before : after
  const path = urlPath(c.filename)
  const patch = patchOf(c)
  return {
    sha: c.status === 'removed' ? c.before : c.after,
    filename: c.filename,
    status: c.status,
    additions: c.additions,
    deletions: c.deletions,
    changes: c.additions + c.deletions,
    blob_url: `https://github.com/${fullName}/blob/${ref}/${path}`,
    raw_url: `https://github.com/${fullName}/raw/${ref}/${path}`,
    contents_url: `https://api.github.com/repos/${fullName}/contents/${path}?ref=${ref}`,
    ...(patch === null ? {} : { patch }),
    ...(c.previous === null ? {} : { previous_filename: c.previous }),
  }
}

/** GraphQL's `PatchStatus` spelling of a change. */
export function changeType(c: FileChange): string {
  return { added: 'ADDED', removed: 'DELETED', modified: 'MODIFIED', renamed: 'RENAMED' }[c.status]
}
