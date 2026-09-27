import { describe, expect, it } from 'vitest'
import { searchPrefilter } from './search_prefilter.ts'

function admits(filter: string | RegExp | null, text: string): boolean {
  if (filter === null) return true
  if (typeof filter === 'string') return text.includes(filter)
  filter.lastIndex = 0
  return filter.test(text)
}

it.each([
  /zzqqxx/i,
  /zzqqxx|qqzzyy/,
  /zz.qxx/,
  /\bzzqqxx\b/,
  /^(zzqqxx|qqzzyy)$/,
  /optional?required/,
  /x*required/,
  /x{0,3}required/,
  /[a-z]+required/,
  /(?:foo|bar)+required/,
  /a\+b/,
  /a{2,3}b/,
  /(?<!\w)(?:needle)(?!\w)/,
  /a(?=b)/,
])('rejects absent required literals for %s', (pat) => {
  const filter = searchPrefilter(pat)
  expect(filter).not.toBeNull()
  expect(admits(filter, 'nothing here\n'.repeat(100))).toBe(false)
})

it.each([/a*/, /a?|b/, /a{0,2}/, /(?:)/, /(a)\1/, /\x61/, /é/, /foo/g, /foo/y])(
  'falls back for nullable or unsupported syntax: %s',
  (pat) => {
    expect(searchPrefilter(pat)).toBeNull()
  },
)

describe.each(['', 'i'])('necessary-condition property, flags=%s', (flags) => {
  it('never rejects a matching line across combinations of regex constructs', () => {
    const atoms = [
      'a',
      'bc',
      '[ab]',
      '.',
      '\\w',
      '(a|bc)',
      '(?:a|)',
      'a?',
      'a*',
      'a+',
      'a{0,2}',
      'a{2}',
      '^a',
      'c$',
      '\\ba\\b',
    ]
    const lines = ['', 'a', 'A', 'bc', 'aa', 'abc', 'abbc', 'c', 'abcabc', ' bca ', 'éa', 'K', 'ſ']
    for (const left of atoms)
      for (const right of atoms) {
        for (const source of [`${left}${right}`, `(?:${left}|${right})`]) {
          const pat = new RegExp(source, flags)
          const filter = searchPrefilter(pat)
          for (const line of lines)
            if (pat.test(line)) {
              expect(admits(filter, `miss\n${line}\nmiss`), `${String(pat)} matching ${line}`).toBe(
                true,
              )
            }
        }
      }
  })
})

it('retains non-ASCII lines when Unicode case folding is enabled', () => {
  const filter = searchPrefilter(/s|k/iu)
  expect(admits(filter, '\xc5\xbf\n')).toBe(true)
  expect(admits(filter, '\xe2\x84\xaa\n')).toBe(true)
})

it('bounds deeply nested and wide analyses', () => {
  expect(searchPrefilter(new RegExp('('.repeat(100) + 'a' + ')'.repeat(100)))).toBeNull()
  expect(
    searchPrefilter(
      new RegExp(Array.from({ length: 100 }, (_, i) => `word${String(i)}`).join('|')),
    ),
  ).toBeNull()
})
