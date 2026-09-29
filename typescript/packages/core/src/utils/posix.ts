export const POSIX_CLASSES: Readonly<Record<string, string>> = {
  alpha: 'A-Za-z',
  digit: '0-9',
  alnum: '0-9A-Za-z',
  upper: 'A-Z',
  lower: 'a-z',
  space: ' \\t\\n\\r\\f\\v',
  blank: ' \\t',
  punct: '!-/:-@\\[-`{-~',
  print: ' -~',
  graph: '!-~',
  cntrl: '\\x00-\\x1f\\x7f',
  xdigit: '0-9A-Fa-f',
}

/** Translate one bracket expression; returns the index past its `]`. */
export function translateBracket(pattern: string, start: number, out: string[]): number {
  let idx = start + 1
  out.push('[')
  if (pattern.charAt(idx) === '^') {
    out.push('^')
    idx += 1
  }
  // A `]` in the first position is a literal member in an ERE, but the
  // host engine would read it as the end of the bracket expression.
  if (pattern.charAt(idx) === ']') {
    out.push('\\]')
    idx += 1
  }
  while (idx < pattern.length) {
    const ch = pattern.charAt(idx)
    if (ch === ']') {
      out.push(']')
      return idx + 1
    }
    if (pattern.startsWith('[:', idx)) {
      const close = pattern.indexOf(':]', idx + 2)
      if (close === -1) {
        out.push('\\[')
        idx += 1
        continue
      }
      const name = pattern.slice(idx + 2, close)
      const expansion = Object.hasOwn(POSIX_CLASSES, name) ? POSIX_CLASSES[name] : undefined
      if (expansion === undefined) throw new SyntaxError('Invalid character class name')
      out.push(expansion)
      idx = close + 2
      continue
    }
    if (ch === '\\' && idx + 1 < pattern.length) {
      out.push(pattern.slice(idx, idx + 2))
      idx += 2
      continue
    }
    if (ch === '[') {
      out.push('\\[')
      idx += 1
      continue
    }
    out.push(ch)
    idx += 1
  }
  throw new SyntaxError('Unmatched [, [^, [:, [., or [=')
}

const INTERVAL = /\{\d+(?:,\d*)?\}/y

/**
 * Expand POSIX brackets while preserving regex operators and escapes. With
 * `nest`, a quantifier stacked on a quantified atom repeats that whole
 * repetition, the way glibc reads an ERE: `a++` is `(a+)+` and `a+?` is
 * `(a+)?`, never a syntax error or the host's lazy form.
 */
export function translateClasses(pattern: string, nest = true): string {
  const out: string[] = []
  const groups: number[] = []
  let atom: number | null = null
  let quantified = false
  let idx = 0
  while (idx < pattern.length) {
    const ch = pattern.charAt(idx)
    INTERVAL.lastIndex = idx
    const interval = ch === '{' ? INTERVAL.exec(pattern) : null
    if ('*+?'.includes(ch) || interval !== null) {
      const token = interval?.[0] ?? ch
      if (nest && quantified && atom !== null)
        out.splice(atom, out.length - atom, '(?:', ...out.slice(atom), ')')
      out.push(token)
      quantified = atom !== null
      idx += token.length
      continue
    }
    quantified = false
    if (ch === '\\' && idx + 1 < pattern.length) {
      atom = out.length
      out.push(pattern.slice(idx, idx + 2))
      idx += 2
    } else if (ch === '[') {
      atom = out.length
      idx = translateBracket(pattern, idx, out)
    } else if (ch === '(') {
      groups.push(out.length)
      atom = null
      out.push(ch)
      idx += 1
    } else if (ch === ')') {
      atom = groups.pop() ?? null
      out.push(ch)
      idx += 1
    } else {
      atom = '|^$'.includes(ch) ? null : out.length
      out.push(ch)
      idx += 1
    }
  }
  return out.join('')
}

export function classCharacters(name: string): string {
  const expansion = Object.hasOwn(POSIX_CLASSES, name) ? POSIX_CLASSES[name] : undefined
  if (expansion === undefined) throw new Error(`tr: invalid character class '${name}'`)
  const pattern = new RegExp('[' + expansion + ']')
  return Array.from({ length: 128 }, (_, n) => String.fromCharCode(n))
    .filter((ch) => pattern.test(ch))
    .join('')
}

/** Compile translated POSIX regex source with deterministic C-locale case folding. */
export function compilePosixRegex(source: string, flags = ''): RegExp {
  const normalized = asciiSpaceEscapes(source)
  return flags.includes('i')
    ? new AsciiIgnoreCaseRegex(normalized, flags)
    : new RegExp(normalized, flags)
}

// JavaScript's \s stays Unicode-aware even without u; Python re.ASCII does not.
const SPACE_ESCAPES: Readonly<Record<string, string>> = {
  '\\s': '\\x09-\\x0d\\x20',
  '\\S': '\\x00-\\x08\\x0e-\\x1f\\x21-\\uffff',
}

function asciiSpaceEscapes(source: string): string {
  return source.replace(/\\[\s\S]|\[(?:\\[\s\S]|[^\]\\])*\]/g, (token) => {
    if (token.startsWith('['))
      return token.replace(/\\[\s\S]/g, (escape) => SPACE_ESCAPES[escape] ?? escape)
    const expansion = SPACE_ESCAPES[token]
    return expansion === undefined ? token : `[${expansion}]`
  })
}

/** Fold only ASCII letters, without changing UTF-16 offsets or non-ASCII text. */
export function foldAscii(text: string): string {
  return text.replace(/[A-Z]+/g, (run) => run.toLowerCase())
}

// Scan complete escapes, classes and named group openers before literal letters.
// Lowercasing regex source directly would turn \\D into \\d and [Z-a] into [z-a].
const FOLD_TOKEN =
  /\\(?:x[\da-fA-F]{2}|u[\da-fA-F]{4}|c[A-Za-z]|k<[^>]+>|[\s\S])|\[(?:\\[\s\S]|[^\]\\])*\]|\(\?<[^=!][^>]*>|[A-Z]/g

function foldRegexSource(source: string): string {
  return source.replace(FOLD_TOKEN, (token) => {
    if (token.startsWith('[')) {
      const bracket = new RegExp(token)
      const negated = token.startsWith('[^')
      let letters = ''
      for (let code = 97; code <= 122; code++) {
        const lower = String.fromCharCode(code)
        const upper = lower.toUpperCase()
        if (negated ? !bracket.test(upper) : bracket.test(upper)) letters += lower
      }
      if (!letters) return token
      return negated ? `(?:(?![${letters}])${token})` : `(?:${token}|[${letters}])`
    }
    if (token.startsWith('(?<') || token.startsWith('\\k<')) return token
    if (/^\\[xu][\da-fA-F]+$/.test(token)) {
      const code = Number.parseInt(token.slice(2), 16)
      return code >= 65 && code <= 90 ? String.fromCharCode(code + 32) : token
    }
    if (token.startsWith('\\')) return token
    return foldAscii(token)
  })
}

/**
 * Match folded text so backreferences also ignore ASCII case. Recover every
 * capture from its original span: grep -o and sed replacements must preserve
 * the input's spelling. The public source/flags remain cloneable through
 * compilePosixRegex; the private matcher never enables JavaScript's Unicode i.
 */
class AsciiIgnoreCaseRegex extends RegExp {
  private readonly folded: RegExp
  private input: string | undefined
  private foldedInput = ''

  constructor(source: string | RegExp, flags?: string) {
    super(source, flags)
    const foldedFlags = this.flags.replace('i', '')
    this.folded = new RegExp(
      foldRegexSource(this.source),
      foldedFlags.includes('d') ? foldedFlags : foldedFlags + 'd',
    )
  }

  override exec(text: string): RegExpExecArray | null {
    this.folded.lastIndex = this.lastIndex
    if (text !== this.input) {
      this.input = text
      this.foldedInput = foldAscii(text)
    }
    const match = this.folded.exec(this.foldedInput)
    this.lastIndex = this.folded.lastIndex
    if (match === null) return null
    const indices = match.indices
    if (indices === undefined) throw new Error('ASCII matcher requires capture indices')
    for (let index = 0; index < match.length; index++) {
      const span = indices[index]
      if (span !== undefined) match[index] = text.slice(span[0], span[1])
    }
    if (match.groups !== undefined && indices.groups !== undefined) {
      for (const name of Object.keys(indices.groups)) {
        const span = indices.groups[name]
        if (span !== undefined) match.groups[name] = text.slice(span[0], span[1])
      }
    }
    match.input = text
    if (!this.hasIndices) delete match.indices
    return match
  }
}
