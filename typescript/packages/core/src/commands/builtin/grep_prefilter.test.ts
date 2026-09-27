import { expect, it } from 'vitest'
import { requiredNeedles } from './grep_prefilter.ts'

it.each([
  [/zzqqxx/i, ['zzqqxx']],
  [/zzqqxx|qqzzyy/, ['zzqqxx', 'qqzzyy']],
  [/(?:zzqqxx)|(?:qqzzyy)/, ['zzqqxx', 'qqzzyy']],
  [/zz.qxx/, ['qxx']],
  [/\bfoo\b/, ['foo']],
  [/foo[0-9]+/, ['foo']],
  [/a?bc/, ['bc']],
  [/a{0,3}bc/, ['bc']],
  [/foo(?:bar)?/, ['foo']],
  [/foo|/, null],
  [/(?:foo)?/, null],
  [/\d+/, null],
  [/(?=foo)/, null],
  [/(foo)\1/, null],
  [/\x66oo/, null],
  [/foo/g, null],
  [/foo/y, null],
  [/é/, null],
] as const)('extracts a conservative requirement for %s', (pat, expected) => {
  expect(requiredNeedles(pat)).toEqual(expected)
})

it('never rejects a matching line across combinations of regex operators', () => {
  const atoms = ['a', 'bc', '[ab]', '.', '\\b', '(?:a|bc)', '(a|)', 'a?b', 'a{0,2}']
  const texts = ['', 'a', 'b', 'c', 'ab', 'abc', 'bc', 'ac', 'bb', 'aabc', 'bcc', 'abcabc']
  for (const left of atoms)
    for (const right of atoms)
      for (const join of ['', '|']) {
        for (const suffix of ['', '?', '*', '+', '{0,2}', '{2}']) {
          const pat = new RegExp(`(?:${left}${join}${right})${suffix}`)
          const needles = requiredNeedles(pat)
          if (needles === null) continue
          for (const text of texts) {
            if (pat.test(text))
              expect(
                needles.some((n) => text.includes(n)),
                `${String(pat)}: ${text}`,
              ).toBe(true)
          }
        }
      }
})
