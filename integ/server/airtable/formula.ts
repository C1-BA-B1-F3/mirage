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

import moment from 'moment'
import type { Moment, unitOfTime } from 'moment'

export type FValue = string | number | boolean | null

export class FormulaSyntaxError extends Error {}

export class UnknownFieldsError extends Error {
  readonly names: string[]

  constructor(names: string[]) {
    super(`unknown fields: ${names.join(', ')}`)
    this.names = names
  }
}

type Kind = 'num' | 'str' | 'field' | 'ident' | 'op' | 'lp' | 'rp' | 'comma'

interface Tok {
  kind: Kind
  text: string
}

type Node =
  | { kind: 'num'; value: number }
  | { kind: 'str'; value: string }
  | { kind: 'field'; ref: string }
  | { kind: 'call'; name: string; args: Node[] }
  | { kind: 'bin'; op: string; left: Node; right: Node }
  | { kind: 'neg'; arg: Node }

// Airtable's scalar formula subset, shared by
// filterByFormula, a view's filter and the formula FIELD, so the three cannot
// disagree about what a formula means. What it accepts:
//
//   literals     'text'  "text"  (backslash escapes)  3  2.5  -1
//   fields       {Field name}  {fldXXXXXXXXXXXXXX}  and a bare single-word
//                name (`Priority = 3`), which Airtable reads as a field too
//   operators    =  !=  <  >  <=  >=  &  +  -  *  /
//                precedence: comparison < & < + - < * / < unary -
//   functions    AND OR NOT TRUE FALSE BLANK RECORD_ID SEARCH FIND LOWER
//                UPPER LEN IF SWITCH LEFT RIGHT MID TRIM SUBSTITUTE
//                CONCATENATE VALUE YEAR MONTH DAY HOUR MINUTE SECOND
//                DATETIME_FORMAT IS_SAME ERROR ISERROR
//                (names are case-insensitive)
//
// An unknown function or syntax error is refused as an invalid formula; a field
// reference that names nothing is refused with the names it could not find.
// Function semantics: https://support.airtable.com/docs/formula-field-reference.
// Dates use UTC and Moment's format tokens, as Airtable does. Parsing accepts
// ISO, RFC 2822 and the US/English dates in the reference, never host-local dates.
// Runtime errors are NaN (excluded by filters and rendered as specialValue by
// cells.ts); operators and ordinary calls propagate them. IF and SWITCH only
// evaluate the selected result, while all branches are validated at compile time.
// Semantics follow Airtable where the subset reaches: a missing cell is BLANK,
// which equals '', 0 and FALSE(); SEARCH is case-insensitive and answers
// blank when it finds nothing, FIND is case-sensitive and answers 0; `=` on
// two strings is exact; a record passes a filter unless its value is 0,
// FALSE, '', BLANK or NaN.
const FUNCS: Record<string, readonly [number, number]> = {
  AND: [1, Number.POSITIVE_INFINITY],
  OR: [1, Number.POSITIVE_INFINITY],
  NOT: [1, 1],
  TRUE: [0, 0],
  FALSE: [0, 0],
  BLANK: [0, 0],
  RECORD_ID: [0, 0],
  SEARCH: [2, 3],
  FIND: [2, 3],
  LOWER: [1, 1],
  UPPER: [1, 1],
  LEN: [1, 1],
  IF: [2, 3],
  SWITCH: [3, Number.POSITIVE_INFINITY],
  LEFT: [2, 2],
  RIGHT: [2, 2],
  MID: [3, 3],
  TRIM: [1, 1],
  SUBSTITUTE: [3, 4],
  CONCATENATE: [1, Number.POSITIVE_INFINITY],
  VALUE: [1, 1],
  YEAR: [1, 1],
  MONTH: [1, 1],
  DAY: [1, 1],
  HOUR: [1, 1],
  MINUTE: [1, 1],
  SECOND: [1, 1],
  DATETIME_FORMAT: [2, 2],
  IS_SAME: [2, 3],
  ERROR: [0, 0],
  ISERROR: [1, 1],
}

const COMPARE = new Set(['=', '!=', '<', '>', '<=', '>='])
const ESCAPES: Record<string, string> = { n: '\n', t: '\t', '\\': '\\', "'": "'", '"': '"' }

function readString(src: string, start: number): [string, number] {
  const quote = src.charAt(start)
  let out = ''
  let i = start + 1
  while (i < src.length) {
    const ch = src.charAt(i)
    if (ch === '\\') {
      const next = src.charAt(i + 1)
      out += ESCAPES[next] ?? next
      i += 2
      continue
    }
    if (ch === quote) return [out, i + 1]
    out += ch
    i += 1
  }
  throw new FormulaSyntaxError('unterminated string')
}

function tokenize(src: string): Tok[] {
  const out: Tok[] = []
  let i = 0
  while (i < src.length) {
    const ch = src.charAt(i)
    if (/\s/.test(ch)) {
      i += 1
      continue
    }
    if (ch === '{') {
      const end = src.indexOf('}', i + 1)
      if (end === -1) throw new FormulaSyntaxError('unterminated field reference')
      out.push({ kind: 'field', text: src.slice(i + 1, end) })
      i = end + 1
      continue
    }
    if (ch === "'" || ch === '"') {
      const [text, next] = readString(src, i)
      out.push({ kind: 'str', text })
      i = next
      continue
    }
    const rest = src.slice(i)
    const num = /^(\d+(\.\d*)?|\.\d+)/.exec(rest)
    if (num !== null) {
      out.push({ kind: 'num', text: num[0] })
      i += num[0].length
      continue
    }
    const ident = /^[A-Za-z_][A-Za-z0-9_]*/.exec(rest)
    if (ident !== null) {
      out.push({ kind: 'ident', text: ident[0] })
      i += ident[0].length
      continue
    }
    const two = rest.slice(0, 2)
    if (two === '!=' || two === '<=' || two === '>=') {
      out.push({ kind: 'op', text: two })
      i += 2
      continue
    }
    if ('=<>&-+*/'.includes(ch)) {
      out.push({ kind: 'op', text: ch })
      i += 1
      continue
    }
    if (ch === '(' || ch === ')' || ch === ',') {
      out.push({ kind: ch === '(' ? 'lp' : ch === ')' ? 'rp' : 'comma', text: ch })
      i += 1
      continue
    }
    throw new FormulaSyntaxError(`unexpected ${ch}`)
  }
  return out
}

class Parser {
  private at = 0
  private readonly toks: Tok[]

  constructor(toks: Tok[]) {
    this.toks = toks
  }

  parse(): Node {
    if (this.toks.length === 0) throw new FormulaSyntaxError('empty formula')
    const node = this.compare()
    if (this.at !== this.toks.length) throw new FormulaSyntaxError('trailing input')
    return node
  }

  private peek(): Tok | undefined {
    return this.toks[this.at]
  }

  private next(): Tok {
    const tok = this.toks[this.at]
    if (tok === undefined) throw new FormulaSyntaxError('unexpected end')
    this.at += 1
    return tok
  }

  private compare(): Node {
    let left = this.concat()
    for (let tok = this.peek(); tok?.kind === 'op' && COMPARE.has(tok.text); tok = this.peek()) {
      this.at += 1
      left = { kind: 'bin', op: tok.text, left, right: this.concat() }
    }
    return left
  }

  private concat(): Node {
    let left = this.additive()
    for (let tok = this.peek(); tok?.kind === 'op' && tok.text === '&'; tok = this.peek()) {
      this.at += 1
      left = { kind: 'bin', op: '&', left, right: this.additive() }
    }
    return left
  }

  private additive(): Node {
    let left = this.product()
    for (
      let tok = this.peek();
      tok?.kind === 'op' && (tok.text === '+' || tok.text === '-');
      tok = this.peek()
    ) {
      this.at += 1
      left = { kind: 'bin', op: tok.text, left, right: this.product() }
    }
    return left
  }

  private product(): Node {
    let left = this.unary()
    for (
      let tok = this.peek();
      tok?.kind === 'op' && (tok.text === '*' || tok.text === '/');
      tok = this.peek()
    ) {
      this.at += 1
      left = { kind: 'bin', op: tok.text, left, right: this.unary() }
    }
    return left
  }

  private unary(): Node {
    const tok = this.peek()
    if (tok?.kind === 'op' && tok.text === '-') {
      this.at += 1
      return { kind: 'neg', arg: this.unary() }
    }
    return this.primary()
  }

  private primary(): Node {
    const tok = this.next()
    switch (tok.kind) {
      case 'num':
        return { kind: 'num', value: Number(tok.text) }
      case 'str':
        return { kind: 'str', value: tok.text }
      case 'field':
        return { kind: 'field', ref: tok.text }
      case 'ident':
        return this.peek()?.kind === 'lp' ? this.call(tok.text) : { kind: 'field', ref: tok.text }
      case 'lp': {
        const inner = this.compare()
        if (this.next().kind !== 'rp') throw new FormulaSyntaxError('expected )')
        return inner
      }
      default:
        throw new FormulaSyntaxError(`unexpected ${tok.text}`)
    }
  }

  private call(raw: string): Node {
    const name = raw.toUpperCase()
    const arity = Object.hasOwn(FUNCS, name) ? FUNCS[name] : undefined
    if (arity === undefined) throw new FormulaSyntaxError(`unknown function ${raw}`)
    this.next()
    const args: Node[] = []
    if (this.peek()?.kind === 'rp') {
      this.next()
    } else {
      for (;;) {
        args.push(this.compare())
        const sep = this.next()
        if (sep.kind === 'rp') break
        if (sep.kind !== 'comma') throw new FormulaSyntaxError('expected , or )')
      }
    }
    if (args.length < arity[0] || args.length > arity[1]) {
      throw new FormulaSyntaxError(`${name} takes ${String(arity[0])}..${String(arity[1])} args`)
    }
    return { kind: 'call', name, args }
  }
}

function refsOf(node: Node, out: string[]): string[] {
  switch (node.kind) {
    case 'field':
      if (!out.includes(node.ref)) out.push(node.ref)
      break
    case 'call':
      for (const arg of node.args) refsOf(arg, out)
      break
    case 'bin':
      refsOf(node.left, out)
      refsOf(node.right, out)
      break
    case 'neg':
      refsOf(node.arg, out)
      break
    default:
      break
  }
  return out
}

export interface Compiled {
  node: Node
  // Each reference as written, resolved to the id of the field it names.
  refs: Map<string, string>
}

// `resolve` answers a field id for a reference, or undefined when it names
// nothing; the refusal then lists every such name, in formula order.
export function compile(src: string, resolve: (ref: string) => string | undefined): Compiled {
  const node = new Parser(tokenize(src)).parse()
  const refs = new Map<string, string>()
  const unknown: string[] = []
  for (const ref of refsOf(node, [])) {
    const id = resolve(ref)
    if (id === undefined) unknown.push(ref)
    else refs.set(ref, id)
  }
  if (unknown.length > 0) throw new UnknownFieldsError(unknown)
  return { node, refs }
}

export interface Env {
  recordId: string
  value: (fieldId: string) => FValue
}

export function toText(v: FValue): string {
  if (v === null) return ''
  if (typeof v === 'boolean') return v ? '1' : '0'
  return typeof v === 'number' ? String(v) : v
}

function numeric(v: FValue): number | null {
  if (v === null) return 0
  if (typeof v === 'number') return v
  if (typeof v === 'boolean') return v ? 1 : 0
  const n = Number(v)
  return v.trim() !== '' && Number.isFinite(n) ? n : null
}

function equal(a: FValue, b: FValue): boolean {
  if (a === null || b === null) {
    const other = a === null ? b : a
    return other === null || other === '' || other === 0 || other === false
  }
  if (typeof a === 'string' && typeof b === 'string') return a === b
  const na = numeric(a)
  const nb = numeric(b)
  if (na !== null && nb !== null) return na === nb
  return toText(a) === toText(b)
}

function order(a: FValue, b: FValue): number {
  const bothText = typeof a === 'string' && typeof b === 'string'
  const na = numeric(a)
  const nb = numeric(b)
  if (!bothText && na !== null && nb !== null) return na - nb
  const ta = toText(a)
  const tb = toText(b)
  return ta < tb ? -1 : ta > tb ? 1 : 0
}

export function truthy(v: FValue): boolean {
  if (v === null || v === false || v === '' || v === 0) return false
  return !isError(v)
}

function isError(v: FValue): boolean {
  return typeof v === 'number' && !Number.isFinite(v)
}

function textSlice(text: FValue, start: FValue, count: FValue, fromRight = false): FValue {
  const at = Math.trunc(numeric(start) ?? Number.NaN)
  const n = Math.trunc(numeric(count) ?? Number.NaN)
  if (!Number.isFinite(at) || !Number.isFinite(n) || at < 1 || n < 0) return Number.NaN
  const chars = Array.from(toText(text))
  const begin = fromRight ? Math.max(0, chars.length - n) : at - 1
  return chars.slice(begin, begin + n).join('')
}

function substitute(args: FValue[]): FValue {
  const [text = null, old = null, replacement = null, which = null] = args
  const source = toText(text)
  const needle = toText(old)
  const value = toText(replacement)
  if (needle === '') return source
  if (args.length === 3) return source.split(needle).join(value)
  const occurrence = Math.trunc(numeric(which) ?? Number.NaN)
  if (!Number.isFinite(occurrence) || occurrence < 1) return Number.NaN
  let from = 0
  for (let n = 1; ; n += 1) {
    const at = source.indexOf(needle, from)
    if (at === -1) return source
    if (n === occurrence) return source.slice(0, at) + value + source.slice(at + needle.length)
    from = at + needle.length
  }
}

function valueOf(text: FValue): number {
  const value = toText(text)
    .trim()
    .replace(/[$£€¥,]/g, '')
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) ? Number(value) : Number.NaN
}

const DATE_FORMATS = [
  moment.ISO_8601,
  moment.RFC_2822,
  ...[
    'M/D/YYYY',
    'MM/DD/YYYY',
    'M/DD/YYYY',
    'MM/D/YYYY',
    'M/D/YY',
    'MM/DD/YY',
    'M/DD/YY',
    'MM/D/YY',
    'D MMM YYYY',
    'D MMMM YYYY',
    'MMM D, YYYY',
    'MMMM D, YYYY',
  ].flatMap((day) => [
    day,
    `${day} H:mm`,
    `${day} H:mm:ss`,
    `${day} HH:mm`,
    `${day} HH:mm:ss`,
    `${day} h:mm A`,
    `${day} h:mm:ss A`,
  ]),
]

function dateOf(value: FValue): Moment {
  return typeof value === 'string'
    ? moment.utc(value.trim(), DATE_FORMATS, 'en', true)
    : moment.invalid()
}

const DATE_UNITS: ReadonlySet<string> = new Set([
  'year',
  'quarter',
  'month',
  'week',
  'isoWeek',
  'day',
  'hour',
  'minute',
  'second',
  'millisecond',
])

function isDateUnit(unit: string | undefined): unit is Extract<unitOfTime.StartOf, string> {
  return unit !== undefined && DATE_UNITS.has(unit)
}

function sameDate(a: FValue, b: FValue, rawUnit: FValue): FValue {
  const unit =
    rawUnit === null ? 'second' : moment.normalizeUnits(toText(rawUnit) as unitOfTime.All)
  const left = dateOf(a)
  const right = dateOf(b)
  if (!left.isValid() || !right.isValid() || !isDateUnit(unit)) {
    return Number.NaN
  }
  return left.isSame(right, unit)
}

function position(needle: FValue, hay: FValue, start: FValue, fold: boolean): number {
  const from = start === null ? 0 : Math.max(0, (numeric(start) ?? 1) - 1)
  const n = fold ? toText(needle).toLowerCase() : toText(needle)
  const h = fold ? toText(hay).toLowerCase() : toText(hay)
  return h.indexOf(n, from)
}

function run(node: Node, env: Env, c: Compiled): FValue {
  switch (node.kind) {
    case 'num':
      return node.value
    case 'str':
      return node.value
    case 'field': {
      const id = c.refs.get(node.ref)
      return id === undefined ? null : env.value(id)
    }
    case 'neg':
      return -(numeric(run(node.arg, env, c)) ?? Number.NaN)
    case 'bin': {
      const l = run(node.left, env, c)
      const r = run(node.right, env, c)
      if (isError(l) || isError(r)) return Number.NaN
      switch (node.op) {
        case '+':
          return (numeric(l) ?? Number.NaN) + (numeric(r) ?? Number.NaN)
        case '-':
          return (numeric(l) ?? Number.NaN) - (numeric(r) ?? Number.NaN)
        case '*':
          return (numeric(l) ?? Number.NaN) * (numeric(r) ?? Number.NaN)
        case '/':
          return numeric(r) === 0
            ? Number.NaN
            : (numeric(l) ?? Number.NaN) / (numeric(r) ?? Number.NaN)
        case '&':
          return toText(l) + toText(r)
        case '=':
          return equal(l, r)
        case '!=':
          return !equal(l, r)
        case '<':
          return order(l, r) < 0
        case '>':
          return order(l, r) > 0
        case '<=':
          return order(l, r) <= 0
        case '>=':
          return order(l, r) >= 0
        default:
          throw new Error(`unimplemented formula operator ${node.op}`)
      }
    }
    case 'call': {
      const lazyArg = (i: number): FValue => {
        const a = node.args[i]
        return a === undefined ? null : run(a, env, c)
      }
      if (node.name === 'IF') {
        const condition = lazyArg(0)
        return isError(condition) ? Number.NaN : lazyArg(truthy(condition) ? 1 : 2)
      }
      if (node.name === 'SWITCH') {
        const value = lazyArg(0)
        if (isError(value)) return Number.NaN
        for (let i = 1; i + 1 < node.args.length; i += 2) {
          const pattern = lazyArg(i)
          if (isError(pattern)) return Number.NaN
          if (equal(value, pattern)) return lazyArg(i + 1)
        }
        return node.args.length % 2 === 0 ? lazyArg(node.args.length - 1) : null
      }
      const args = node.args.map((a) => run(a, env, c))
      if (node.name === 'ISERROR') return isError(args[0] ?? null)
      if (args.some(isError)) return Number.NaN
      const arg = (i: number): FValue => args[i] ?? null
      switch (node.name) {
        case 'AND':
          return args.every(truthy)
        case 'OR':
          return args.some(truthy)
        case 'NOT':
          return !truthy(arg(0))
        case 'TRUE':
          return true
        case 'FALSE':
          return false
        case 'BLANK':
          return null
        case 'ERROR':
          return Number.NaN
        case 'RECORD_ID':
          return env.recordId
        case 'SEARCH': {
          const at = position(arg(0), arg(1), arg(2), true)
          return at === -1 ? null : at + 1
        }
        case 'FIND':
          return position(arg(0), arg(1), arg(2), false) + 1
        case 'LOWER':
          return toText(arg(0)).toLowerCase()
        case 'UPPER':
          return toText(arg(0)).toUpperCase()
        case 'LEN':
          return Array.from(toText(arg(0))).length
        case 'LEFT':
          return textSlice(arg(0), 1, arg(1))
        case 'RIGHT':
          return textSlice(arg(0), 1, arg(1), true)
        case 'MID':
          return textSlice(arg(0), arg(1), arg(2))
        case 'TRIM':
          return toText(arg(0)).trim()
        case 'SUBSTITUTE':
          return substitute(args)
        case 'CONCATENATE':
          return args.map(toText).join('')
        case 'VALUE':
          return valueOf(arg(0))
        case 'YEAR':
          return dateOf(arg(0)).year()
        case 'MONTH':
          return dateOf(arg(0)).month() + 1
        case 'DAY':
          return dateOf(arg(0)).date()
        case 'HOUR':
          return dateOf(arg(0)).hour()
        case 'MINUTE':
          return dateOf(arg(0)).minute()
        case 'SECOND':
          return dateOf(arg(0)).second()
        case 'DATETIME_FORMAT': {
          const date = dateOf(arg(0))
          return date.isValid() ? date.format(toText(arg(1))) : Number.NaN
        }
        case 'IS_SAME':
          return sameDate(arg(0), arg(1), arg(2))
        default:
          throw new Error(`unimplemented formula function ${node.name}`)
      }
    }
    default:
      return null
  }
}

export function evaluate(c: Compiled, env: Env): FValue {
  const value = run(c.node, env, c)
  return isError(value) ? Number.NaN : value
}
