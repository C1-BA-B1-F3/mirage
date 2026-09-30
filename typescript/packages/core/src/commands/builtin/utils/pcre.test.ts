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

import { describe, expect, it } from 'vitest'
import { PcreError, hostFlags, matchStart, matchText, translatePcre, userGroups } from './pcre.ts'

function compiled(pattern: string, unicode = false, ignoreCase = false): RegExp {
  const translated = translatePcre(pattern, unicode, ignoreCase)
  return new RegExp(translated.source, hostFlags(translated.source, translated.ignoreCase) + 'g')
}

function only(pattern: string, text: string, unicode = false, ignoreCase = false): string[] {
  const re = compiled(pattern, unicode, ignoreCase)
  const found: string[] = []
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    const piece = matchText(m)
    if (piece) found.push(piece)
    if (m[0] === '') re.lastIndex += 1
  }
  return found
}

// grep 3.11 -oP (PCRE2 10.46, no UCP) unless the row says unicode, which is
// ripgrep 14.1.1's -oP (UTF and UCP); the rows are `test_pcre.py`'s own.
describe('translatePcre', () => {
  it.each([
    ['\\d+', 'abc 123 x45', ['123', '45'], false],
    ['(?<=id=)\\d+', 'id=42 name=x', ['42'], false],
    ['name=\\K\\w+', 'id=42 name=x', ['x'], false],
    ['\\x{00a0}', 'a\u00a0b', ['\u00a0'], false],
    ['\\t', 'a\tb', ['\t'], false],
    ['\\h', 'a b', [' '], false],
    ['\\Q.\\E', 'a.b', ['.'], false],
    ['\\Q.b*', 'a.b*c', ['.b*'], false],
    ['(a)\\g{1}', 'aa', ['aa'], false],
    ['(a)\\g1', 'aa', ['aa'], false],
    ['(a)\\g{-1}', 'aa', ['aa'], false],
    ['(?<x>a)\\k<x>', 'aa', ['aa'], false],
    ['(?P<x>a)(?P=x)', 'aa', ['aa'], false],
    ["(?'x'a)\\k'x'", 'aa', ['aa'], false],
    ['(?<x>a)\\k{x}', 'aa', ['aa'], false],
    ['(?>a+)a', 'aaa', [], false],
    ['a++a', 'aaa', [], false],
    ['a*+', 'aaa', ['aaa'], false],
    ['a?+a', 'aaa', ['aa'], false],
    ['(?i)a', 'Aa', ['A', 'a'], false],
    ['(?i:A)a', 'Aa', ['Aa'], false],
    ['a(?i)b', 'Ab', [], false],
    ['(?i)a(?-i)B', 'AB', ['AB'], false],
    ['\\Aab\\z', 'ab', ['ab'], false],
    ['\\Aab\\Z', 'ab', ['ab'], false],
    ['\\w+', 'a\u00e9', ['a'], false],
    ['[[:alpha:]]+', 'a\u00e91', ['a'], false],
    ['[\\d]+', 'ab12', ['12'], false],
    ['[^\\d]+', 'ab12', ['ab'], false],
    ['a\\Kb|x', 'ab', ['b'], false],
    ['a\\Ka', 'aaa', ['a'], false],
    ['foo=\\K\\d', 'foo=1 foo=2', ['1', '2'], false],
    ['a(?#comment)b', 'abc', ['ab'], false],
    ['(?x) a b # c', 'abc', ['ab'], false],
    ['(?m)^a', 'abc', ['a'], false],
    ['\\N', 'aXb', ['a', 'X', 'b'], false],
    ['\\101', 'A1', ['A'], false],
    ['[[:^alpha:]b]', 'ab', ['b'], false],
    ['\\pL+', 'ab', ['ab'], false],
    ['\\P{L}', 'ab1', ['1'], false],
    ['\\p{L&}+', 'ab', ['ab'], false],
    ['\\p{Xan}+', 'ab1', ['ab1'], false],
    ['a{,2}', 'aaa', ['aa', 'a'], false],
    ['a{x}', 'a{x}', ['a{x}'], false],
    ['a{,}', 'a{,}', ['a{,}'], false],
    ['(?<=a|bc)x', 'bcx ax', ['x', 'x'], false],
    ['(a(?i)b|c)', 'aC', ['C'], false],
    ['(?x)a\\ b', 'a b', ['a b'], false],
    ['[[:<:]]a', 'a', ['a'], false],
    ['(?i)a(?^)A', 'aA', ['aA'], false],
    ['(*UTF)a', 'a', ['a'], false],
    ['(?C1)a', 'a', ['a'], false],
    ['(?=a)*a', 'ab', ['a'], false],
    ['a{1,2}?', 'aaa', ['a', 'a', 'a'], false],
    ['\\w+', 'a\u00e9', ['a\u00e9'], true],
    ['\\d+', 'a\u06635', ['\u06635'], true],
    ['\\s', 'a\u00a0b', ['\u00a0'], true],
    ['\\s', 'a\u180eb', ['\u180e'], true],
    ['\\w+', 'a\u00b2b', ['a\u00b2b'], true],
    ['\\w+', 'a\u200cb', ['a', 'b'], true],
    ['[[:alpha:]]+', 'a\u00e9', ['a\u00e9'], true],
    ['\\b\u00e9', 'a\u00e9', [], true],
    ['\\x{e9}', 'a\u00e9', ['\u00e9'], true],
  ] as [string, string, string[], boolean][])('%j over %j', (pattern, text, found, unicode) => {
    expect(only(pattern, text, unicode)).toEqual(found)
  })

  it('folds a caseless back-reference on the host', () => {
    expect(only('(a)\\1', 'aA', false, true)).toEqual(['aA'])
    expect(only('(?i)(a)\\1', 'aA')).toEqual(['aA'])
    expect(only('\u00e9', '\u00c9\u00e9', true, true)).toEqual(['\u00c9', '\u00e9'])
  })

  it('moves the reported start past a \\K', () => {
    const m = compiled('a\\Kbc').exec('abc')
    expect(m).not.toBeNull()
    if (m !== null) expect([matchStart(m), matchText(m)]).toEqual([1, 'bc'])
  })

  it('skips the \\K of a branch that did not match', () => {
    expect(only('foo=\\K\\d|a\\Ka', 'foo=1 foo=2 aaa')).toEqual(['1', '2', 'a'])
  })

  it('numbers the user groups past the markers', () => {
    expect(userGroups(compiled('a\\K(b)(?<n>c)'))).toEqual([2, 3])
  })

  it.each([
    ['(', 'missing closing parenthesis', 1],
    ['(?:()', 'missing closing parenthesis', 5],
    ['(?:a))', 'unmatched closing parenthesis', 5],
    ['(?:[a)', 'missing terminating ] for character class', 6],
    ['a\\', '\\ at end of pattern', 2],
    ['(?:*a)', 'quantifier does not follow a repeatable item', 3],
    ['(?:a{2,1})', 'numbers out of order in {} quantifier', 8],
    ['(?:(?<=a+)b)', 'length of lookbehind assertion is not limited', 3],
    ['(?:(a)\\2)', 'reference to non-existent subpattern', 7],
    ['(?:(?z))', 'unrecognized character after (? or (?-', 5],
    ['(?:\\x{110000})', 'character code point value in \\x{} or \\o{} is too large', 12],
    ['a**', 'quantifier does not follow a repeatable item', 2],
    ['\\b*a', 'quantifier does not follow a repeatable item', 2],
    ['a{2}{3}', 'quantifier does not follow a repeatable item', 6],
    ['[\\d-z]', 'invalid range in character class', 4],
    ['[z-a]', 'range out of order in character class', 3],
    ['[[:foo:]]', 'unknown POSIX class name', 8],
    ['\\x{zz}', 'non-hex character in \\x{} (closing brace missing?)', 3],
    ['\\o{8}', 'non-octal character in \\o{} (closing brace missing?)', 3],
    ['\\x', 'digits missing after \\x or in \\x{} or \\o{} or \\N{U+}', 2],
    ['\\y', 'unrecognized character follows \\', 1],
    ['\\p', 'malformed \\P or \\p sequence', 2],
    ['[\\N]', '\\N is not supported in a class', 3],
    ['a{65536}', 'number too big in {} quantifier', 7],
    ['(?<', 'subpattern name expected', 3],
    ['(?<a', 'syntax error in subpattern name (missing terminator?)', 4],
    ['(?<1a>x)', 'subpattern name must start with a non-digit', 3],
    ['(?<a>x)(?<a>y)', 'two named subpatterns have the same name (PCRE2_DUPNAMES not set)', 12],
    ['\\k<zz>', 'reference to non-existent subpattern', 3],
    ['(?#x', 'missing ) after (?# comment', 4],
    [
      '(?<=a\\Kb)c',
      '\\K is not allowed in lookarounds (but see PCRE2_EXTRA_ALLOW_LOOKAROUND_BSK)',
      10,
    ],
    ['\\N{U+41}', '\\N{U+dddd} is supported only in Unicode (UTF) mode', 2],
    ['\\c', '\\c at end of pattern', 2],
    ['\\8', 'reference to non-existent subpattern', 1],
    ['(?', 'missing closing parenthesis', 2],
    [
      '\\ga',
      '\\g is not followed by a braced, angle-bracketed, or quoted name/number or by a plain number',
      2,
    ],
  ] as [string, string, number][])('refuses %j', (pattern, message, offset) => {
    let caught: unknown = null
    try {
      translatePcre(pattern)
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(PcreError)
    expect([(caught as PcreError).message, (caught as PcreError).offset]).toEqual([message, offset])
  })

  it.each([
    '\\Gab',
    '\\X',
    '(ab)(?1)',
    '(?R)?a',
    '(a)\\g<1>',
    '(?|(a)|(b))',
    '(a)(?(1)b|c)',
    '\\p{Greek}',
    '(?<=a?b)c',
    '(?*a)',
    '(*SKIP)a',
    '(a)(?i)\\1',
  ])('refuses %j as nothing a host can express', (pattern) => {
    expect(() => translatePcre(pattern)).toThrow(/is not supported in mirage$/)
  })
})
