import { describe, expect, it } from 'vitest'
import { LONGEST, requiredNeedles } from './grep_prefilter.ts'

const LATIN1 = new TextDecoder('latin1')
const ENC = new TextEncoder()

it.each([
  [/zzqqxx/, ['zzqqxx']],
  [/zzqqxx|qqzzyy/, ['zzqqxx', 'qqzzyy']],
  [/(?:zzqqxx)|(?:qqzzyy)/, ['zzqqxx', 'qqzzyy']],
  [/^(zzqqxx|qqzzyy)$/, ['zzqqxx', 'qqzzyy']],
  [/zz.qxx/, ['qxx']],
  [/\bfoo\b/, ['foo']],
  [/(?<!\w)(?:needle)(?!\w)/, ['needle']],
  [/a(?=b)c/, ['ac']],
  [/foo[0-9]+/, ['foo']],
  [/a?bc/, ['bc']],
  [/x*required/, ['required']],
  [/a{0,3}bc/, ['bc']],
  [/a{2,3}b/, ['a']],
  [/a\+b/, ['a+b']],
  [/a\/b/, ['a/b']],
  [/[a-z]+required/, ['required']],
  [/(?:foo|bar)+required/, ['required']],
  [/foo(?:bar)?/, ['foo']],
  [/(?<name>foo)bar/, ['foobar']],
  [/foo\tbar/, ['foo']],
  [/(?:ab|ab)c/, ['abc']],
  [/Foo|FOO|bar/i, ['foo', 'bar']],
  [/needle/m, ['needle']],
  [new RegExp('needle', 'v'), ['needle']],
] as const)('extracts a conservative requirement for %s', (pat, expected) => {
  expect(requiredNeedles(pat)).toEqual(expected)
})

it.each([
  /foo|/,
  /(?:foo)?/,
  /a*/,
  /a?|b/,
  /a{0,2}/,
  /(?:)/,
  /\d+/,
  /(foo)\1/,
  /(?<name>a)\k<name>/,
  /\x66oo/,
  new RegExp('\\u0066oo'),
  /a{,3}b/,
  /a{b/,
  new RegExp('[]foo'),
  /[^]foo/,
  /[x[]foo/,
  /é/,
  /foo/g,
  /foo/y,
  /s/iu,
  new RegExp('s', 'iv'),
  new RegExp('('.repeat(100) + 'a' + ')'.repeat(100)),
  new RegExp(Array.from({ length: 100 }, (_, i) => `word${String(i)}`).join('|')),
])('falls back on nullable or unknown syntax: %s', (pat) => {
  expect(requiredNeedles(pat)).toBeNull()
})

it('keeps the needles Unicode folding cannot reach', () => {
  // Only the Kelvin sign and `ſ` fold onto ASCII letters under `iu`, so
  // `needle` still narrows.
  expect(requiredNeedles(/Needle/iu)).toEqual(['needle'])
  expect(requiredNeedles(/kin/iu)).toBeNull()
})

it('bounds the source and builds long literals once', () => {
  expect(requiredNeedles(new RegExp('a'.repeat(LONGEST)))).toEqual(['a'.repeat(LONGEST)])
  expect(requiredNeedles(new RegExp('a'.repeat(LONGEST + 1)))).toBeNull()
})

function admits(needles: readonly string[] | null, line: string, pat: RegExp): boolean {
  const view = LATIN1.decode(ENC.encode(line))
  const text = pat.ignoreCase ? view.toLowerCase() : view
  return needles === null || needles.some((needle) => text.includes(needle))
}

describe.each(['', 'i', 'u', 'iu'])('necessary-condition property, flags=%s', (flags) => {
  it('never rejects a matching line', () => {
    const atoms = [
      'a',
      'bc',
      'A',
      '[ab]',
      '.',
      '\\w',
      '\\b',
      '\\.',
      '(a|bc)',
      '(?:a|)',
      'a?',
      'a*',
      'a+',
      'a{0,2}',
      'a{2}',
      'a+?',
      '^a',
      'c$',
      '\\ba\\b',
      '(?=b)',
      '(?!a)',
      '(?<=a)',
      '(?<!b)',
      '(?<n>a)',
      'a?b',
    ]
    const lines = [
      '',
      'a',
      'A',
      'b',
      'c',
      'ab',
      'bc',
      'Bc',
      'aa',
      'ac',
      'bb',
      'abc',
      'abbc',
      'aabc',
      'bcc',
      'abcabc',
      ' bca ',
      'a.b',
      'éa',
      'K',
      'k',
      'K',
      'ſ',
      'S',
      'BC',
    ]
    for (const left of atoms)
      for (const right of atoms) {
        if (left === '(?<n>a)' && right === left) continue
        const sources = [`${left}${right}`, `(?:${left}|${right})`]
        for (const suffix of ['?', '*', '+', '{0,2}', '{2}'])
          sources.push(`(?:${left}${right})${suffix}`)
        for (const source of sources) {
          const pat = new RegExp(source, flags)
          const needles = requiredNeedles(pat)
          for (const line of lines)
            if (pat.test(line))
              expect(admits(needles, line, pat), `${String(pat)} matching ${line}`).toBe(true)
        }
      }
  })
})
