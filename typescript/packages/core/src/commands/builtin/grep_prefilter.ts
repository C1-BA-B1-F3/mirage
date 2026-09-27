interface Required {
  literal: string | null
  needles: string[]
}

const UNKNOWN: Required = { literal: null, needles: [] }

function literal(text: string): Required {
  return { literal: text, needles: text ? [text] : [] }
}

function strength(needles: readonly string[]): number {
  return needles.length ? Math.min(...needles.map((s) => s.length)) : 0
}

/** A bounded, deliberately partial parser: unsupported syntax disables skipping. */
class RequiredLiterals {
  private at = 0
  valid = true

  constructor(private readonly source: string) {}

  parse(depth = 0): Required {
    if (depth > 32) {
      this.valid = false
      return UNKNOWN
    }
    const branches: Required[] = []
    let best: string[] = []
    let run = ''
    let exact: string | null = ''
    while (this.at < this.source.length && this.source[this.at] !== ')') {
      if (this.source[this.at] === '|') {
        branches.push({ literal: exact, needles: best })
        best = []
        run = ''
        exact = ''
        this.at++
        continue
      }
      let atom = this.atom(depth)
      if (!this.valid) return UNKNOWN
      const rest = this.source.slice(this.at)
      const quantifier = /^(?:[?*+]|\{([0-9]+)(?:,[0-9]*)?\})/.exec(rest)
      if (quantifier !== null) {
        this.at += quantifier[0].length
        const optional =
          /^[?*]/.test(quantifier[0]) ||
          (quantifier[1] !== undefined && Number(quantifier[1]) === 0)
        atom = optional ? UNKNOWN : { literal: null, needles: atom.needles }
        if (this.source[this.at] === '?') this.at++
      }
      exact = exact !== null && atom.literal !== null ? exact + atom.literal : null
      run = atom.literal === null ? '' : run + atom.literal
      const candidate = run ? [run] : atom.needles
      if (strength(candidate) > strength(best)) best = candidate
    }
    branches.push({ literal: exact, needles: best })
    if (depth === 0 && this.at !== this.source.length) this.valid = false
    if (branches.length === 1) return branches[0] ?? UNKNOWN
    if (branches.some((b) => b.needles.length === 0)) return UNKNOWN
    const needles = [...new Set(branches.flatMap((b) => b.needles))]
    return needles.length <= 64 ? { literal: null, needles } : UNKNOWN
  }

  private atom(depth: number): Required {
    const char = this.source.charAt(this.at++)
    if (char === '(') {
      let assertion = false
      if (['?=', '?!', '?<=', '?<!'].some((prefix) => this.source.startsWith(prefix, this.at))) {
        assertion = true
        this.at += this.source.startsWith('?<', this.at) ? 3 : 2
      } else if (this.source.startsWith('?:', this.at)) this.at += 2
      else if (this.source[this.at] === '?') {
        this.valid = false
        return UNKNOWN
      }
      const group = this.parse(depth + 1)
      if (this.source[this.at++] !== ')') this.valid = false
      return assertion ? UNKNOWN : group
    }
    if (char === '[') {
      if (this.source[this.at] === '^') this.at++
      if (this.source[this.at] === ']') this.at++
      while (this.at < this.source.length) {
        const member = this.source[this.at++]
        if (member === ']') return UNKNOWN
        if (member === '\\') this.at++
        if (member === '[') break
      }
      this.valid = false
      return UNKNOWN
    }
    if (char === '\\') {
      const escaped = this.source.charAt(this.at++)
      if ('bB'.includes(escaped) && escaped) return literal('')
      if ('dDsSwWnrtfv'.includes(escaped) && escaped) return UNKNOWN
      if (escaped && !/[a-zA-Z0-9]/.test(escaped)) return literal(escaped)
      this.valid = false
      return UNKNOWN
    }
    if (char === '.') return UNKNOWN
    if (char === '^' || char === '$') return literal('')
    if ('*+?{}'.includes(char)) {
      this.valid = false
      return UNKNOWN
    }
    return literal(char)
  }
}

/** At least one returned byte-view literal occurs in every matching line. */
export function requiredNeedles(pat: RegExp): string[] | null {
  if (pat.global || pat.sticky || pat.source.length > 4096 || /[^\x20-\x7e]/.test(pat.source))
    return null
  const parser = new RequiredLiterals(pat.source)
  const required = parser.parse().needles
  if (!parser.valid || required.length === 0) return null
  const needles = pat.ignoreCase ? required.map((s) => s.toLowerCase()) : required
  // Unicode case folding can select a non-ASCII spelling of an ASCII letter.
  // Keep such lines for the real matcher; this byte view is never output.
  if (pat.ignoreCase && (pat.unicode || pat.flags.includes('v'))) {
    const view = new TextDecoder('latin1')
    const encoder = new TextEncoder()
    for (const [letter, spelling] of [
      ['s', 'ſ'],
      ['k', 'K'],
    ] as const) {
      if (needles.some((s) => s.includes(letter)))
        needles.push(view.decode(encoder.encode(spelling)).toLowerCase())
    }
  }
  return needles
}
