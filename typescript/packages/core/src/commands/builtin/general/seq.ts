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

import type { PathSpec } from '../../../types.ts'
import type { Accessor } from '../../../accessor/base.ts'
import { IOResult } from '../../../io/types.ts'
import { command, type CommandFnResult, type CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { extraOperandError, missingOperandError } from '../../spec/usage.ts'
import { UsageError } from '../../errors.ts'
import { quoteText } from '../../quote.ts'
import { formatFloat } from '../../../core/awk/value.ts'
import { CommandName } from '../../spec/types.ts'
import { FlagView } from '../../spec/flag_view.ts'

const ENC = new TextEncoder()

// GNU seq's long_double_format: one floating directive, its flags and an
// optional L, with nothing but %% around it.
const FORMAT_DIRECTIVE = /([-+#0 ']*)([0-9]*)(?:\.([0-9]*))?(L?)/y
const FLOAT_CONVERSIONS = 'efgaEFGA'

// A `-f` format GNU accepts, split around its one directive. Mirrors
// Python's SeqFormat.
export interface SeqFormat {
  readonly prefix: string
  readonly flags: string
  readonly width: string
  readonly precision: string | null
  readonly conversion: string
  readonly suffix: string
}

// Index of the first `%` that is not half of `%%`, or -1.
function lonePercent(text: string): number {
  let i = 0
  while (i < text.length) {
    if (text[i] === '%') {
      if (text[i + 1] !== '%') return i
      i += 2
      continue
    }
    i += 1
  }
  return -1
}

// GNU seq's `-f` check: exactly one floating `%` directive. Mirrors Python's
// parse_format.
export function parseFormat(fmt: string): SeqFormat {
  const shown = `'${quoteText(fmt)}'`
  const start = lonePercent(fmt)
  if (start < 0) throw new UsageError(`seq: format ${shown} has no % directive`, 1)
  FORMAT_DIRECTIVE.lastIndex = start + 1
  const match = FORMAT_DIRECTIVE.exec(fmt)
  const end = FORMAT_DIRECTIVE.lastIndex
  const conversion = fmt[end]
  if (conversion === undefined) throw new UsageError(`seq: format ${shown} ends in %`, 1)
  if (!FLOAT_CONVERSIONS.includes(conversion)) {
    throw new UsageError(`seq: format ${shown} has unknown %${conversion} directive`, 1)
  }
  const suffix = fmt.slice(end + 1)
  if (lonePercent(suffix) >= 0) {
    throw new UsageError(`seq: format ${shown} has too many % directives`, 1)
  }
  return {
    prefix: fmt.slice(0, start),
    flags: match?.[1] ?? '',
    width: match?.[2] ?? '',
    precision: match?.[3] ?? null,
    conversion,
    suffix,
  }
}

// `value` through a `%a` directive, as glibc renders it: the hex digits
// round half to even at the precision without renormalizing (`%.0a` of 3
// is `0x2p+1`), `#` keeps the point and `0` pads after `0x`. GNU's value is
// a long double, so a value needing more than a double's 53 bits shows
// fewer digits here. Mirrors Python's _hex_float.
function hexFloat(value: number, spec: SeqFormat): string {
  const flags = spec.flags
  const sign =
    value < 0 || Object.is(value, -0)
      ? '-'
      : flags.includes('+')
        ? '+'
        : flags.includes(' ')
          ? ' '
          : ''
  const magnitude = Math.abs(value)
  let zero = false
  let body: string
  if (!Number.isFinite(magnitude)) {
    body = Number.isNaN(magnitude) ? 'nan' : 'inf'
  } else {
    const view = new DataView(new ArrayBuffer(8))
    view.setFloat64(0, magnitude)
    const bits = view.getBigUint64(0)
    const biased = Number(bits >> 52n)
    const fraction = bits & ((1n << 52n) - 1n)
    let lead = biased === 0 ? '0' : '1'
    const exponent = biased === 0 ? (fraction === 0n ? 0 : -1022) : biased - 1023
    let digits = fraction.toString(16).padStart(13, '0')
    if (spec.precision === null) {
      digits = digits.replace(/0+$/, '')
    } else {
      const places = Number(spec.precision || '0')
      if (places >= digits.length) {
        digits = digits.padEnd(places, '0')
      } else {
        let kept = BigInt(`0x${lead}${digits.slice(0, places)}`)
        const rest = BigInt(`0x${digits.slice(places)}`)
        const half = 8n << BigInt(4 * (digits.length - places - 1))
        if (rest > half || (rest === half && kept % 2n === 1n)) kept += 1n
        const text = kept.toString(16).padStart(places + 1, '0')
        lead = text.slice(0, text.length - places)
        digits = text.slice(text.length - places)
      }
    }
    const point = digits !== '' || flags.includes('#') ? '.' : ''
    body = `0x${lead}${point}${digits}p${exponent < 0 ? '-' : '+'}${String(Math.abs(exponent))}`
    zero = flags.includes('0') && !flags.includes('-')
  }
  if (spec.conversion === 'A') body = body.toUpperCase()
  const width = spec.width === '' ? 0 : Number(spec.width)
  if (flags.includes('-')) return (sign + body).padEnd(width)
  if (zero) return sign + body.slice(0, 2) + body.slice(2).padStart(width - sign.length - 2, '0')
  return (sign + body).padStart(width)
}

// One value through a `-f` format, as C's printf renders it. Mirrors
// Python's render.
export function render(spec: SeqFormat, value: number): string {
  const body = 'aA'.includes(spec.conversion)
    ? hexFloat(value, spec)
    : formatFloat(
        spec.conversion,
        value,
        spec.flags.replaceAll("'", ''),
        spec.width === '' ? null : Number(spec.width),
        spec.precision === null ? null : Number(spec.precision || '0'),
      )
  return spec.prefix.replaceAll('%%', '%') + body + spec.suffix.replaceAll('%%', '%')
}

function zeroPad(value: number, width: number): string {
  // Pad with leading zeros after any sign, matching Python str.zfill / GNU seq.
  const s = String(value)
  if (s.startsWith('-')) return '-' + s.slice(1).padStart(width - 1, '0')
  return s.padStart(width, '0')
}

function seqGenerate(
  texts: string[],
  separator: string,
  width: string | null,
  fmt: string | null,
): string {
  const nums = texts.map((t) => Number.parseFloat(t))
  let first: number
  let step: number
  let last: number
  if (nums.length === 1) {
    first = 1
    step = 1
    last = Math.trunc(nums[0] ?? 0)
  } else if (nums.length === 2) {
    first = Math.trunc(nums[0] ?? 0)
    step = 1
    last = Math.trunc(nums[1] ?? 0)
  } else {
    first = Math.trunc(nums[0] ?? 0)
    step = Math.trunc(nums[1] ?? 1)
    last = Math.trunc(nums[2] ?? 0)
  }
  const values: number[] = []
  let cur = first
  if (step > 0) {
    while (cur <= last) {
      values.push(cur)
      cur += step
    }
  } else if (step < 0) {
    while (cur >= last) {
      values.push(cur)
      cur += step
    }
  }
  let parts: string[]
  if (fmt !== null) {
    const spec = parseFormat(fmt)
    parts = values.map((v) => render(spec, v))
  } else if (width !== null) {
    const w = values.length > 0 ? Math.max(...values.map((v) => String(v).length)) : 1
    parts = values.map((v) => zeroPad(v, w))
  } else {
    parts = values.map((v) => String(v))
  }
  return parts.join(separator) + '\n'
}

function seqCommand(
  _accessor: Accessor,
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
): CommandFnResult {
  if (texts.length === 0) throw missingOperandError(CommandName.SEQ, null)
  if (texts.length > 3) throw extraOperandError(CommandName.SEQ, texts[3] ?? '')
  const fl = new FlagView(opts.flags, specOf('seq'))
  const s = fl.asStr('s') ?? null
  // -w is declared boolean, so any occurrence means equal width and the
  // old string branch was unreachable; Python passes the bool straight in.
  const w = fl.asBool('w') ? '' : null
  const f = fl.asStr('f') ?? null
  const separator = s ?? '\n'
  const result = seqGenerate(texts, separator, w, f)
  return [ENC.encode(result), new IOResult()]
}

export const GENERAL_SEQ = command({
  name: 'seq',
  vfs: null,
  spec: specOf('seq'),
  fn: seqCommand,
})
