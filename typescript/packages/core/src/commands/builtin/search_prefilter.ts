interface Summary {
  // exact is the consumed text, when fixed; needles is a disjunction that
  // every match must contain. An empty disjunction gives no information.
  exact: string | null
  needles: string[]
}
const UNKNOWN: Summary = { exact: null, needles: [] }
const EMPTY: Summary = { exact: '', needles: [] }
const LIMIT = 64

function literal(text: string): Summary {
  return { exact: text, needles: text ? [text] : [] }
}

function score(part: Summary): number {
  return part.needles.length ? Math.min(...part.needles.map((s) => s.length)) : 0
}

function sequence(left: Summary, right: Summary): Summary {
  if (left.exact !== null && right.exact !== null) return literal(left.exact + right.exact)
  return { exact: null, needles: score(left) >= score(right) ? left.needles : right.needles }
}

function alternative(left: Summary, right: Summary): Summary {
  if (left.exact !== null && left.exact === right.exact) return left
  if (!left.needles.length || !right.needles.length) return UNKNOWN
  const needles = [...new Set([...left.needles, ...right.needles])]
  return needles.length <= LIMIT ? { exact: null, needles } : UNKNOWN
}

// This is a necessary-condition analysis, not a regex interpreter. Unknown
// syntax disables the filter; unknown atoms cannot contribute a requirement.
class Literals {
  private at = 0
  private safe = true
  constructor(private readonly source: string) {}

  read(): string[] {
    const result = this.expression(0)
    return this.safe && this.at === this.source.length ? result.needles : []
  }

  private expression(depth: number): Summary {
    if (depth > LIMIT) {
      this.safe = false
      return UNKNOWN
    }
    let result = this.concatenation(depth)
    while (this.safe && this.source[this.at] === '|') {
      this.at++
      result = alternative(result, this.concatenation(depth))
    }
    return result
  }

  private concatenation(depth: number): Summary {
    let result = EMPTY
    let run = EMPTY
    while (
      this.safe &&
      this.at < this.source.length &&
      !')|'.includes(this.source.charAt(this.at))
    ) {
      let atom = this.atom(depth)
      const next = this.source.charAt(this.at)
      if (next && '*+?{'.includes(next)) {
        this.at++
        let required = next === '+'
        if (next === '{') {
          const match = /^(\d+)(?:,(\d*)?)?\}/.exec(this.source.slice(this.at))
          if (match === null) {
            this.safe = false
            return UNKNOWN
          }
          required = Number(match[1]) > 0
          this.at += match[0].length
        }
        atom = required ? { exact: null, needles: atom.needles } : UNKNOWN
        if (this.source[this.at] === '?') this.at++
      }
      // Keep adjacent exact atoms together even after an opaque atom.
      if (atom.exact !== null) run = sequence(run, atom)
      else {
        result = sequence(sequence(result, run), atom)
        run = EMPTY
      }
    }
    return sequence(result, run)
  }

  private atom(depth: number): Summary {
    const char = this.source.charAt(this.at++)
    if (char === '(') {
      const assertion = ['?=', '?!', '?<=', '?<!'].find((prefix) =>
        this.source.startsWith(prefix, this.at),
      )
      if (assertion !== undefined) this.at += assertion.length
      else if (this.source.startsWith('?:', this.at)) this.at += 2
      else if (this.source[this.at] === '?') {
        this.safe = false
        return UNKNOWN
      }
      const value = this.expression(depth + 1)
      if (this.source[this.at++] !== ')') this.safe = false
      return assertion === undefined ? value : EMPTY
    }
    if (char === '[') {
      if (this.source[this.at] === '^') this.at++
      // Leading ] is dialect-sensitive. Refuse it rather than guess.
      if (this.source[this.at] === ']') {
        this.safe = false
        return UNKNOWN
      }
      while (this.at < this.source.length) {
        const member = this.source[this.at++]
        if (member === ']') return UNKNOWN
        if (member === '\\') this.at++
      }
      this.safe = false
      return UNKNOWN
    }
    if (char === '\\') {
      const escaped = this.source.charAt(this.at++)
      if ('bB'.includes(escaped) && escaped) return EMPTY
      if ('dDsSwW'.includes(escaped) && escaped) return UNKNOWN
      if (!escaped || /[a-zA-Z0-9]/.test(escaped)) {
        this.safe = false
        return UNKNOWN
      }
      return literal(escaped)
    }
    if (char === '.') return UNKNOWN
    if (char === '^' || char === '$') return EMPTY
    if ('*+?{}'.includes(char)) {
      this.safe = false
      return UNKNOWN
    }
    return literal(char)
  }
}

/** A byte-view search whose absence proves no line can match. */
export function searchPrefilter(pat: RegExp): string | RegExp | null {
  if (pat.global || pat.sticky || pat.flags.includes('v') || /[^\x20-\x7e]/.test(pat.source))
    return null
  const needles = new Literals(pat.source).read()
  if (!needles.length) return null
  if (!pat.ignoreCase && needles.length === 1) return needles[0] ?? null
  const alternatives = needles.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  // Unicode case folding can match non-ASCII bytes (ſ, K). Retain every
  // non-ASCII line in that mode; the line matcher owns Unicode semantics.
  if (pat.ignoreCase && pat.unicode) alternatives.push('[\\x80-\\uffff]')
  return new RegExp(alternatives.join('|'), pat.ignoreCase ? 'gi' : 'g')
}
