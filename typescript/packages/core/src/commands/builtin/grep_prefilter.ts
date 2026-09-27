interface Required {
  exact: string | null
  needles: string[]
}

const UNKNOWN: Required = { exact: null, needles: [] }
const CACHE = new WeakMap<RegExp, string | RegExp | null>()
const BYTE_VIEW = new TextDecoder('latin1')
const ENC = new TextEncoder()

function literal(text: string): Required {
  return { exact: text, needles: text === '' ? [] : [text] }
}

function sequence(parts: Required[]): Required {
  let run = ''
  let best: string[] = []
  let strength = 0
  let exact = ''
  for (const part of [...parts, UNKNOWN]) {
    if (part.exact !== null) {
      run += part.exact
      exact += part.exact
    } else {
      if (run.length > strength) {
        best = [run]
        strength = run.length
      }
      run = ''
      const score = part.needles.length === 0 ? 0 : Math.min(...part.needles.map((n) => n.length))
      if (score > strength) {
        best = part.needles
        strength = score
      }
    }
  }
  const allExact = parts.every((p) => p.exact !== null)
  return allExact ? literal(exact) : { exact: null, needles: best }
}

class Parser {
  at = 0
  safe = true

  constructor(private readonly source: string) {}

  expression(depth = 0): Required {
    if (depth > 32) {
      this.safe = false
      return UNKNOWN
    }
    const branches: Required[] = []
    let parts: Required[] = []
    while (this.at < this.source.length && this.safe) {
      const char = this.source[this.at] ?? ''
      if (char === ')') break
      this.at++
      if (char === '|') {
        branches.push(sequence(parts))
        parts = []
        continue
      }
      let atom = UNKNOWN
      if (char === '(') {
        let assertion = false
        if (['?=', '?!', '?<=', '?<!'].some((prefix) => this.source.startsWith(prefix, this.at))) {
          assertion = true
          this.at += this.source.startsWith('?<', this.at) ? 3 : 2
        } else if (this.source.startsWith('?:', this.at)) this.at += 2
        else if (this.source.startsWith('?', this.at)) {
          this.safe = false
          break
        }
        atom = this.expression(depth + 1)
        if (this.source[this.at] !== ')') {
          this.safe = false
          break
        }
        this.at++
        if (assertion) atom = UNKNOWN
      } else if (char === '[') {
        if (this.source[this.at] === '^') this.at++
        if (this.source[this.at] === ']') this.at++
        while (this.at < this.source.length && this.source[this.at] !== ']') {
          this.at += this.source[this.at] === '\\' ? 2 : 1
        }
        this.at++
      } else if (char === '\\') {
        const escaped = this.source[this.at++] ?? ''
        if (!['b', 'B', 'A', 'Z', 'z', 'd', 'D', 's', 'S', 'w', 'W'].includes(escaped)) {
          if (escaped !== '' && !/[a-z0-9]/i.test(escaped) && escaped >= ' ' && escaped <= '~') {
            atom = literal(escaped)
          } else {
            this.safe = false
            break
          }
        }
      } else if ('*+?{}'.includes(char)) {
        this.safe = false
        break
      } else if (!'.^$'.includes(char) && char >= ' ' && char <= '~') {
        atom = literal(char)
      }
      const quantifier = this.source[this.at] ?? ''
      if (quantifier !== '' && '*+?'.includes(quantifier)) {
        this.at++
        atom = { exact: null, needles: quantifier === '+' ? atom.needles : [] }
      } else if (quantifier === '{') {
        const repeat = /^\{([0-9]+)(?:,([0-9]*))?\}/.exec(this.source.slice(this.at))
        if (repeat === null) {
          this.safe = false
          break
        }
        this.at += repeat[0].length
        atom = { exact: null, needles: Number(repeat[1]) > 0 ? atom.needles : [] }
      }
      if (
        quantifier !== '' &&
        '*+?{'.includes(quantifier) &&
        ['?', '+'].includes(this.source[this.at] ?? '')
      )
        this.at++
      parts.push(atom)
    }
    branches.push(sequence(parts))
    if (branches.length === 1) return branches[0] ?? UNKNOWN
    if (branches.some((b) => b.needles.length === 0)) return UNKNOWN
    const needles = [...new Set(branches.flatMap((b) => b.needles))]
    return needles.length <= 64 ? { exact: null, needles } : UNKNOWN
  }
}

/**
 * A necessary (never sufficient) byte test for a decoded-line match.
 * Concatenation keeps a required run; alternation retains every branch.
 * Unsupported syntax and unbounded plans fall back to the full matcher.
 */
export function requiredLiteral(pat: RegExp): string | RegExp | null {
  const cached = CACHE.get(pat)
  if (cached !== undefined) return cached
  const parser = new Parser(pat.source)
  const { needles } = parser.expression()
  let result: string | RegExp | null = null
  if (
    parser.safe &&
    parser.at === pat.source.length &&
    needles.length > 0 &&
    !pat.sticky &&
    !pat.global &&
    !pat.flags.includes('v')
  ) {
    if (!pat.ignoreCase && needles.length === 1) result = needles[0] ?? null
    else {
      const alternatives = needles.map(escape)
      if (pat.ignoreCase && pat.unicode) {
        const letters = needles.join('').toLowerCase()
        for (const [letter, folds] of [
          ['s', 'ſ'],
          ['k', 'K'],
        ] as const) {
          if (letters.includes(letter))
            alternatives.push(escape(BYTE_VIEW.decode(ENC.encode(folds))))
        }
      }
      result = new RegExp(alternatives.join('|'), 'g' + (pat.ignoreCase ? 'i' : ''))
    }
  }
  CACHE.set(pat, result)
  return result
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
