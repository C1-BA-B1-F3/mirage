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

export const MAX_CODE_POINT = 0x10ffff
export const SURROGATE_LOW = 0xd800
export const SURROGATE_HIGH = 0xdfff

// The characters a host pattern must escape to mean themselves, outside and
// inside a bracket expression. Both are the subset python `re` and
// JavaScript's `u`-flag `RegExp` agree on: under `u` an identity escape is
// only legal for a syntax character, so nothing else is escaped.
const OUTSIDE_SPECIAL = '\\^$.|?*+()[]{}/'
const INSIDE_SPECIAL = '\\]^-['

export type Range = readonly [number, number]

/**
 * A set of code points as sorted, disjoint, non-adjacent ranges.
 *
 * The algebra a character class needs -- union, intersection, difference,
 * symmetric difference and negation -- done on the ranges rather than left to
 * the host, which spells none of the set operations and whose own negation
 * also matches a lone surrogate. Negation is over the Unicode scalar values,
 * as a Rust or PCRE2 class is, so a surrogate (an undecodable byte in
 * mirage's text) is never a member of a negated class. Mirrors `CharSet` in
 * `charset.py`.
 */
export class CharSet {
  readonly ranges: readonly Range[]

  constructor(ranges: readonly Range[] = []) {
    this.ranges = ranges
  }

  // The set of the given ranges, normalized.
  static of(...ranges: Range[]): CharSet {
    const sorted = ranges.filter((r) => r[0] <= r[1]).sort((a, b) => a[0] - b[0] || a[1] - b[1])
    const merged: [number, number][] = []
    for (const [low, high] of sorted) {
      const last = merged[merged.length - 1]
      if (last !== undefined && low <= last[1] + 1) last[1] = Math.max(last[1], high)
      else merged.push([low, high])
    }
    return new CharSet(merged)
  }

  // The set of the given code points.
  static chars(...codePoints: number[]): CharSet {
    return CharSet.of(...codePoints.map((cp): Range => [cp, cp]))
  }

  union(other: CharSet): CharSet {
    return CharSet.of(...this.ranges, ...other.ranges)
  }

  // Every scalar value not in the set.
  negate(): CharSet {
    const out: Range[] = []
    let low = 0
    for (const [start, end] of this.ranges) {
      if (start > low) out.push([low, start - 1])
      low = end + 1
    }
    if (low <= MAX_CODE_POINT) out.push([low, MAX_CODE_POINT])
    return CharSet.of(...out).minusSurrogates()
  }

  // The set without the surrogate block.
  minusSurrogates(): CharSet {
    const out: Range[] = []
    for (const [low, high] of this.ranges) {
      if (high < SURROGATE_LOW || low > SURROGATE_HIGH) {
        out.push([low, high])
        continue
      }
      if (low < SURROGATE_LOW) out.push([low, SURROGATE_LOW - 1])
      if (high > SURROGATE_HIGH) out.push([SURROGATE_HIGH + 1, high])
    }
    return new CharSet(out)
  }

  intersect(other: CharSet): CharSet {
    const out: Range[] = []
    let i = 0
    let j = 0
    while (i < this.ranges.length && j < other.ranges.length) {
      const a = this.ranges[i] ?? [0, -1]
      const b = other.ranges[j] ?? [0, -1]
      const low = Math.max(a[0], b[0])
      const high = Math.min(a[1], b[1])
      if (low <= high) out.push([low, high])
      if (a[1] < b[1]) i += 1
      else j += 1
    }
    return new CharSet(out)
  }

  // Every code point in this set and not the other.
  minus(other: CharSet): CharSet {
    return this.intersect(other.negate().union(this.surrogates()))
  }

  // Every code point in exactly one of the sets.
  xor(other: CharSet): CharSet {
    return this.minus(other).union(other.minus(this))
  }

  // The part of this set inside the surrogate block.
  surrogates(): CharSet {
    return this.intersect(CharSet.of([SURROGATE_LOW, SURROGATE_HIGH]))
  }

  contains(cp: number): boolean {
    let low = 0
    let high = this.ranges.length
    while (low < high) {
      const mid = (low + high) >> 1
      const [start, end] = this.ranges[mid] ?? [0, -1]
      if (cp < start) high = mid
      else if (cp > end) low = mid + 1
      else return true
    }
    return false
  }

  isEmpty(): boolean {
    return this.ranges.length === 0
  }

  // The one member of a one-member set, else null.
  single(): number | null {
    const only = this.ranges[0]
    if (this.ranges.length === 1 && only !== undefined && only[0] === only[1]) return only[0]
    return null
  }

  equals(other: CharSet): boolean {
    if (this.ranges.length !== other.ranges.length) return false
    return this.ranges.every((r, i) => {
      const o = other.ranges[i]
      return r[0] === o?.[0] && r[1] === o[1]
    })
  }
}

export const ALL = CharSet.of([0, MAX_CODE_POINT]).minusSurrogates()

/**
 * One code point as a `u`-flag `RegExp` reads it inside or out. A BMP code
 * point is `\uXXXX`, which the non-`u` bracket test in `AsciiIgnoreCaseRegex`
 * reads the same way; only an astral one needs `\u{...}`.
 */
function hostCodePoint(cp: number): string {
  if (cp <= 0xff) return '\\x' + cp.toString(16).padStart(2, '0')
  if (cp <= 0xffff) return '\\u' + cp.toString(16).padStart(4, '0')
  return '\\u{' + cp.toString(16) + '}'
}

/**
 * One literal code point outside a bracket expression. Printable ASCII stays
 * readable (the grep prefilter reads host source for its needles and gives up
 * at an escaped letter); everything else is a numeric escape.
 */
export function hostChar(cp: number): string {
  if (cp >= 0x20 && cp <= 0x7e) {
    const ch = String.fromCharCode(cp)
    return OUTSIDE_SPECIAL.includes(ch) ? '\\' + ch : ch
  }
  return hostCodePoint(cp)
}

// One code point inside a host bracket expression.
function classMember(cp: number): string {
  if (cp >= 0x20 && cp <= 0x7e) {
    const ch = String.fromCharCode(cp)
    return INSIDE_SPECIAL.includes(ch) ? '\\' + ch : ch
  }
  return hostCodePoint(cp)
}

// The members of a host bracket expression for some ranges.
export function classBody(ranges: readonly Range[]): string {
  const parts: string[] = []
  for (const [low, high] of ranges) {
    if (low === high) parts.push(classMember(low))
    else if (high === low + 1) parts.push(classMember(low) + classMember(high))
    else parts.push(classMember(low) + '-' + classMember(high))
  }
  return parts.join('')
}

/**
 * A set as one host atom that matches exactly its members: the shorter of the
 * positive and the negated spelling; the negated one names the surrogate
 * block among the excluded, so a host that reads a lone surrogate as a
 * character still never matches one.
 */
export function hostClass(cs: CharSet): string {
  const single = cs.single()
  if (single !== null) return hostChar(single)
  if (cs.isEmpty()) return '[^' + classBody([[0, MAX_CODE_POINT]]) + ']'
  const complement = cs.negate()
  if (complement.ranges.length < cs.ranges.length) {
    const excluded = complement.union(CharSet.of([SURROGATE_LOW, SURROGATE_HIGH]))
    return '[^' + classBody(excluded.ranges) + ']'
  }
  return '[' + classBody(cs.ranges) + ']'
}
