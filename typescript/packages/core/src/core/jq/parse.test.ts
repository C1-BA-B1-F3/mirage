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

import { loadJq, type Jq } from 'jq-wasm'
import { describe, expect, it } from 'vitest'
import { JqParser, MAX_PARSING_DEPTH, decodeUtf8, numberValue, utf8Missing } from './parse.ts'
import { JqParseError, NO_VALUE } from './types.ts'

const ENC = new TextEncoder()
const FFFD = String.fromCharCode(0xfffd)
const BOM = String.fromCharCode(0xfeff)
const CONTROL = 'Invalid string: control characters from U+0000 through U+001F must be escaped'

/** A parse error as the drains below record it. */
interface Err {
  readonly error: string
}

function err(message: string): Err {
  return { error: message }
}

function isErr(value: unknown): value is Err {
  return typeof value === 'object' && value !== null && 'error' in value
}

/** Bytes spelled one character per byte, the way Python's b'...' spells them. */
function b(text: string): Uint8Array {
  const out = new Uint8Array(text.length)
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i)
    if (code > 0xff) throw new Error(`not a byte: ${String(code)}`)
    out[i] = code
  }
  return out
}

function label(text: string): string {
  const shown = JSON.stringify(text)
  return shown.length > 48 ? `${shown.slice(0, 45)}...` : shown
}

// An RS under --seq can end a call with nothing to hand back while the
// buffer still holds bytes, so pull until the buffer is used up.
function drain(parser: JqParser, seq: boolean): unknown[] {
  const out: unknown[] = []
  for (;;) {
    const value = parser.next()
    if (value === NO_VALUE) {
      if (parser.remaining() > 0) continue
      return out
    }
    if (value instanceof JqParseError) {
      out.push(err(value.message))
      if (!seq) return out
      continue
    }
    out.push(value)
  }
}

function whole(data: Uint8Array, seq = false, streaming = false): unknown[] {
  const parser = new JqParser(seq, streaming)
  parser.feed(data, false)
  return drain(parser, seq)
}

function bytewise(data: Uint8Array, seq = false, streaming = false): unknown[] {
  const parser = new JqParser(seq, streaming)
  const out: unknown[] = []
  for (let i = 0; i < data.length; i += 1) {
    parser.feed(data.subarray(i, i + 1), true)
    const got = drain(parser, seq)
    out.push(...got)
    if (!seq && got.some(isErr)) return out
  }
  parser.feed(new Uint8Array(0), false)
  return [...out, ...drain(parser, seq)]
}

const READS = [whole, bytewise]

type Case = readonly [string, readonly unknown[], string | null]
type SeqCase = readonly [string, readonly unknown[]]

// Every case below is jq 1.8.2's own output: the values its parser yields,
// then the report of the error that stopped it, if one did. Inputs are
// bytes, one character per byte.
const NORMAL: readonly Case[] = [
  ['1 [', [1], 'Unfinished JSON term at EOF at line 1, column 3'],
  ['truefalse', [], 'Invalid literal at EOF at line 1, column 9'],
  ['1true', [], 'Invalid numeric literal at EOF at line 1, column 5'],
  ['true x', [true], 'Invalid numeric literal at EOF at line 1, column 6'],
  ['1]', [], "Unmatched ']' at line 1, column 2"],
  ['1 ]', [1], "Unmatched ']' at line 1, column 3"],
  ['1 } 2', [1], "Unmatched '}' at line 1, column 3"],
  ['[1]]', [[1]], "Unmatched ']' at line 1, column 4"],
  ['{"a":1}}', [{ a: 1 }], "Unmatched '}' at line 1, column 8"],
  ['[1,]', [], 'Expected another array element at line 1, column 4'],
  ['{"a" 1}', [], 'Expected separator between values at line 1, column 7'],
  ['{"a":1 "b":2}', [], 'Expected separator between values at line 1, column 10'],
  ['[1 2]', [], 'Expected separator between values at line 1, column 5'],
  ['{1:2}', [], 'Object keys must be strings at line 1, column 3'],
  ['[1:2]', [], "':' not as part of an object at line 1, column 3"],
  ['["a":1]', [], "':' not as part of an object at line 1, column 5"],
  ['{"a":}', [], "Unmatched '}' at line 1, column 6"],
  ['{,}', [], "Expected value before ',' at line 1, column 2"],
  ['[,1]', [], "Expected value before ',' at line 1, column 2"],
  ['1,2', [], "Expected value before ',' at line 1, column 2"],
  ['{"a",1}', [], 'Objects must consist of key:value pairs at line 1, column 5'],
  ['{"a"}', [], 'Objects must consist of key:value pairs at line 1, column 5'],
  ['[1}', [], 'Objects must consist of key:value pairs at line 1, column 3'],
  ['{"a":1]', [], "Unmatched ']' at line 1, column 7"],
  ['{"a":1,}', [], 'Expected another key-value pair at line 1, column 8'],
  [']', [], "Unmatched ']' at line 1, column 1"],
  ['}', [], "Unmatched '}' at line 1, column 1"],
  [':', [], "Expected string key before ':' at line 1, column 1"],
  [',', [], "Expected value before ',' at line 1, column 1"],
  ['"a\x01b"', [], `${CONTROL} at line 1, column 5`],
  ['"\x01"\n', [], `${CONTROL} at line 1, column 3`],
  ['"a\x00b"', [], `${CONTROL} at line 1, column 5`],
  ['"\\ud800"', [], 'Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 8'],
  ['"\\ud800\\u0041"', [], 'Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 14'],
  ['"\\ud800x"', [], 'Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 9'],
  ['"\\u12"', [], 'Invalid \\uXXXX escape at line 1, column 6'],
  ['"\\u12zz"', [], 'Invalid characters in \\uXXXX escape at line 1, column 8'],
  ['"\\x"', [], 'Invalid escape at line 1, column 4'],
  ['"abc', [], 'Unfinished string at EOF at line 1, column 4'],
  ['"a\\', [], 'Unfinished string at EOF at line 1, column 3'],
  ["'a'", [], 'Invalid string literal; expected ", but got \' at EOF at line 1, column 3'],
  ['nul', [], 'Invalid literal at EOF at line 1, column 3'],
  ['fals', [], 'Invalid literal at EOF at line 1, column 4'],
  ['nulll', [], 'Invalid literal at EOF at line 1, column 5'],
  ['truex', [], 'Invalid literal at EOF at line 1, column 5'],
  ['n', [], 'Invalid numeric literal at EOF at line 1, column 1'],
  ['nu', [], 'Invalid literal at EOF at line 1, column 2'],
  ['nan1 ', [], 'Invalid numeric literal at line 1, column 5'],
  ['sNaN1 ', [], 'Invalid numeric literal at line 1, column 6'],
  ['infinit ', [], 'Invalid numeric literal at line 1, column 8'],
  ['infinityx ', [], 'Invalid numeric literal at line 1, column 10'],
  ['1e ', [], 'Invalid numeric literal at line 1, column 3'],
  ['1e+ ', [], 'Invalid numeric literal at line 1, column 4'],
  ['. ', [], 'Invalid numeric literal at line 1, column 2'],
  ['- ', [], 'Invalid numeric literal at line 1, column 2'],
  ['1.2.3 ', [], 'Invalid numeric literal at line 1, column 6'],
  ['0x10 ', [], 'Invalid numeric literal at line 1, column 5'],
  ['--1 ', [], 'Invalid numeric literal at line 1, column 4'],
  ['1\x002 ', [1], null],
  ['\x00', [], 'Invalid numeric literal at EOF at line 1, column 1'],
  ['\xff', [], 'Invalid numeric literal at EOF at line 1, column 1'],
  ['[1,\x1e2', [], 'Invalid numeric literal at EOF at line 1, column 5'],
  ['{"a":1', [], 'Unfinished JSON term at EOF at line 1, column 6'],
  ['{"a"', [], 'Unfinished JSON term at EOF at line 1, column 4'],
  ['{"a":', [], 'Unfinished JSON term at EOF at line 1, column 5'],
  ['{', [], 'Unfinished JSON term at EOF at line 1, column 1'],
  ['{"a":1} {"a":', [{ a: 1 }], 'Unfinished JSON term at EOF at line 1, column 13'],
  ['[1,2]\n\n\n{', [[1, 2]], 'Unfinished JSON term at EOF at line 4, column 1'],
  ['['.repeat(10001), [], 'Exceeds depth limit for parsing at line 1, column 10001'],
  ['['.repeat(10000), [], 'Unfinished JSON term at EOF at line 1, column 10000'],
  ['\xef\xbb\xbf1', [1], null],
  ['\xef\xbb1', [], 'Malformed BOM'],
  ['\xef\xbb\xbf\xef\xbb\xbf1', [], 'Invalid numeric literal at EOF at line 1, column 4'],
  ['', [], null],
  ['  \n\t ', [], null],
  ['1.', [1], null],
  ['{"b":1,"1":2}', [{ b: 1, 1: 2 }], null],
  ['"\xf0\x80\x80\x80"', [FFFD], null],
  ['"\xed\xa0\x80"', [FFFD], null],
  ['"\xf4\x90\x80\x80"', [FFFD], null],
  ['"\xe2\x82"', [FFFD], null],
  ['"\xc0\x80"', [FFFD + FFFD], null],
  ['"\xe2\x82x"', [`${FFFD}x`], null],
  ['"\xe2a"', [FFFD], null],
  ['"\\udc00"', [FFFD], null],
  ['"\xef\xbb\xbfa"', [`${BOM}a`], null],
  ['"\\ud83d\\ude00" "\\u00e9\\n\\/"', [String.fromCodePoint(0x1f600), '\xe9\n/'], null],
]

const STREAMING: readonly Case[] = [
  [
    '[1,[2,3],{"a":4}]',
    [[[0], 1], [[1, 0], 2], [[1, 1], 3], [[1, 1]], [[2, 'a'], 4], [[2, 'a']], [[2]]],
    null,
  ],
  ['{"a":[1,', [[['a', 0], 1]], 'Unfinished JSON term at EOF at line 1, column 8'],
  ['[1,2', [[[0], 1]], 'Unfinished JSON term at EOF at line 1, column 4'],
  [
    '1 2 "x" [] {}',
    [
      [[], 1],
      [[], 2],
      [[], 'x'],
      [[], []],
      [[], {}],
    ],
    null,
  ],
  ['{"a" 1}', [], 'Expected separator between values at line 1, column 7'],
  ['[1 2]', [], 'Expected separator between values at line 1, column 5'],
  [']', [], "Unmatched ']' at the top-level at line 1, column 1"],
  ['{]', [], "Unmatched ']' in the middle of an object at line 1, column 2"],
  ['[1}', [], "Unmatched '}' in the middle of an array at line 1, column 3"],
  ['{"a":1]', [], "Unmatched ']' in the middle of an object at line 1, column 7"],
  ['{"a":}', [], 'Missing value in key:value pair at line 1, column 6'],
  ['{,}', [], "Expected value before ',' at line 1, column 2"],
  ['[1,]', [[[0], 1]], 'Expected another array element at line 1, column 4'],
  ['{"a":1,}', [[['a'], 1]], 'Expected another key:value pair at line 1, column 8'],
  ['{["a"]}', [], "Expected string key after '{', not '[' at line 1, column 2"],
  [
    '{"a":1,["b"]}',
    [[['a'], 1]],
    "Expected string key after ',' in object, not '[' at line 1, column 8",
  ],
  ['{{}}', [], "Expected string key after '{', not '{' at line 1, column 2"],
  [
    '{"a":1,{}}',
    [[['a'], 1]],
    "Expected string key after ',' in object, not '{' at line 1, column 8",
  ],
  ['1 : 2', [[[], 1]], "':' not as part of an object at line 1, column 3"],
  ['[1:2]', [], "':' not as part of an object at line 1, column 3"],
  ['{1:2}', [], 'Object keys must be strings at line 1, column 3'],
  ['{"a" "b"}', [], 'Expected separator between values at line 1, column 8'],
  [',', [], "Expected value before ',' at line 1, column 1"],
  ['{"a":1 "b":2}', [], 'Expected separator between values at line 1, column 10'],
  ['[[1]', [[[0, 0], 1], [[0, 0]]], 'Unfinished JSON term at EOF at line 1, column 4'],
  ['[1] 2 x', [[[0], 1], [[0]], [[], 2]], 'Invalid numeric literal at EOF at line 1, column 7'],
  ['{"a":1,"a":2}', [[['a'], 1], [['a'], 2], [['a']]], null],
]

// --seq reports a parse error and reads on, so its errors sit among the
// values in the order the parser met them.
const SEQ: readonly SeqCase[] = [
  ['\x1e1\n\x1e[2]\n', [1, [2]]],
  ['\x1e1\n\x1e[2', [1, err('Unfinished JSON term at EOF at line 2, column 3')]],
  ['\x1e{"a":1}\x1e{"b":2}\n', [{ a: 1 }, { b: 2 }]],
  ['\x1e[1,\x1e2\n', [err('Truncated value at line 1, column 5'), 2]],
  [
    '\x1e[1 2]\n\x1e3\n',
    [err('Expected separator between values at line 1, column 6 (need RS to resync)'), 3],
  ],
  [
    '\x1e[1 2] 3\n',
    [err('Expected separator between values at line 1, column 6 (need RS to resync)'), 3],
  ],
  ['\x1e"abc\n', [err('Unfinished string at EOF at line 2, column 0')]],
  ['\x1etrue\x1e', [err('Truncated value at line 1, column 6')]],
  ['\x1e"a"', ['a']],
  ['\x1e"\x1e1\n', [1]],
  ['\x1e"123\x1e', [err('Potentially truncated top-level numeric value at line 1, column 6')]],
  ['\x1e1 \x1e2 ', [1, 2]],
  ['\x1e1 2\n', [1, 2]],
  ['1 2', [err('Unfinished abandoned text at EOF at line 1, column 3')]],
  ['1 2 [', [err('Unfinished abandoned text at EOF at line 1, column 5')]],
  ['\x1e\x1e1\n', [1]],
  ['x\x1e1\n', [1]],
  ['[\x1e1\n', [1]],
  ['\x1e1\x1e', [err('Potentially truncated top-level numeric value at line 1, column 3')]],
  ['\x1e{"a":1}', [{ a: 1 }]],
  ['\xef\xbb', [err('Unfinished abandoned text at EOF at line 1, column 0')]],
  [
    '\x1e1\x1e[\x1e2',
    [
      err('Potentially truncated top-level numeric value at line 1, column 3'),
      err('Truncated value at line 1, column 5'),
      err('Potentially truncated top-level numeric value at EOF at line 1, column 6'),
    ],
  ],
]

const SEQ_STREAMING: readonly SeqCase[] = [
  ['\x1e1\n', [[[], 1]]],
  ['\x1e[1,2]\n', [[[0], 1], [[1], 2], [[1]]]],
  ['\x1e[1,2\x1e3\n', [[[0], 1], err('Truncated value at line 1, column 6'), [[], 3]]],
]

function expected(values: readonly unknown[], error: string | null): unknown[] {
  return error === null ? [...values] : [...values, err(error)]
}

describe('JqParser', () => {
  for (const [input, values, error] of NORMAL) {
    it(`reads ${label(input)} as jq does`, () => {
      for (const read of READS) expect(read(b(input))).toEqual(expected(values, error))
    })
  }

  for (const [input, values, error] of STREAMING) {
    it(`streams ${label(input)} as jq --stream does`, () => {
      for (const read of READS) {
        expect(read(b(input), false, true)).toEqual(expected(values, error))
      }
    })
  }

  for (const [input, want] of SEQ) {
    it(`reads ${label(input)} as jq --seq does, reading on past an error`, () => {
      for (const read of READS) expect(read(b(input), true)).toEqual(want)
    })
  }

  for (const [input, want] of SEQ_STREAMING) {
    it(`streams ${label(input)} as jq --seq --stream does`, () => {
      for (const read of READS) expect(read(b(input), true, true)).toEqual(want)
    })
  }

  it('takes the numbers decNumber reads', () => {
    const got = whole(
      b(
        'nan NaN Infinity -Infinity +1 .5 1. 01 -0 1.000 1e2 100000000000000000001 ' +
          '-nan snan inf INF iNfInItY nan0 ',
      ),
    )
    expect(got).toEqual([
      NaN,
      NaN,
      Infinity,
      -Infinity,
      1,
      0.5,
      1,
      1,
      -0,
      1,
      100,
      1e20,
      NaN,
      NaN,
      Infinity,
      Infinity,
      Infinity,
      NaN,
    ])
  })

  it('keeps __proto__ an ordinary own key', () => {
    const [value] = whole(b('{"__proto__":1,"a":[]}'))
    expect(Object.getPrototypeOf(value)).toBe(Object.prototype)
    expect(Object.getOwnPropertyDescriptor(value, '__proto__')?.value).toBe(1)
    expect(Object.keys(value as object)).toEqual(['__proto__', 'a'])
  })

  it('keeps a duplicate key in its first place with its last value', () => {
    expect(Object.entries(whole(b('{"a":1,"b":2,"a":3}'))[0] as object)).toEqual([
      ['a', 3],
      ['b', 2],
    ])
  })

  it('stops for good after a parse error outside --seq', () => {
    const parser = new JqParser()
    parser.feed(b('1] 2 3'), false)
    expect(parser.next()).toEqual(new JqParseError("Unmatched ']' at line 1, column 2"))
    expect(parser.remaining()).toBe(0)
    expect(parser.next()).toBe(NO_VALUE)
  })

  it('hands back nothing before a buffer and after the end', () => {
    const parser = new JqParser()
    expect(parser.next()).toBe(NO_VALUE)
    parser.feed(b('7'), false)
    expect(parser.next()).toBe(7)
    expect(parser.next()).toBe(NO_VALUE)
  })

  it("holds --stream to the ordinary parser's depth limit, counted in containers", () => {
    // jq's streaming parser has no depth limit; mirage's has the ordinary
    // parser's.
    const tooDeep = 'Exceeds depth limit for parsing at line 1, column '
    expect(whole(b('['.repeat(10001)), false, true)).toEqual([err(`${tooDeep}10001`)])
    expect(whole(b('{"a":'.repeat(10001)), false, true)).toEqual([err(`${tooDeep}50001`)])
    const deepest = `${'['.repeat(MAX_PARSING_DEPTH)}${']'.repeat(MAX_PARSING_DEPTH)}`
    const events = whole(b(deepest), false, true)
    expect(events).toHaveLength(MAX_PARSING_DEPTH)
    expect(events[0]).toEqual([Array<number>(MAX_PARSING_DEPTH - 1).fill(0), []])
    expect(events[events.length - 1]).toEqual([[0]])
  })

  it('nests as deep as jq and no deeper', () => {
    const deepest = `${'['.repeat(MAX_PARSING_DEPTH)}${']'.repeat(MAX_PARSING_DEPTH)}`
    let value = whole(b(deepest))[0]
    for (let depth = 0; depth < MAX_PARSING_DEPTH; depth += 1) {
      expect(Array.isArray(value)).toBe(true)
      value = (value as unknown[])[0]
    }
    expect(value).toBeUndefined()
  })
})

describe('JqParser, for a caller that parses whole values itself', () => {
  it('says when it stands clean between values', () => {
    const parser = new JqParser()
    expect(parser.clean()).toBe(true)
    parser.feed(b('1'), true)
    expect(parser.next()).toBe(NO_VALUE)
    expect(parser.clean()).toBe(false)
    parser.feed(b(' '), true)
    expect(parser.next()).toBe(1)
    expect(parser.clean()).toBe(true)
    parser.feed(b('[1, 2'), true)
    expect(parser.remaining()).toBe(5)
    expect(parser.next()).toBe(NO_VALUE)
    expect(parser.clean()).toBe(false)
    expect(new JqParser(true).clean()).toBe(false)
    expect(new JqParser(false, true).clean()).toBe(false)
  })

  it('is never clean past a malformed BOM', () => {
    const parser = new JqParser()
    parser.feed(b('\xef\xbb1'), true)
    expect(parser.clean()).toBe(false)
    expect(parser.next()).toEqual(new JqParseError('Malformed BOM'))
  })

  it('says how much of a BOM it would strip', () => {
    const parser = new JqParser()
    expect(parser.bomSkip(b('\xef\xbb\xbf1'))).toBe(3)
    expect(parser.bomSkip(b('1'))).toBe(0)
    expect(parser.bomSkip(b(''))).toBe(0)
    expect(parser.bomSkip(b('\xef\xbb'))).toBeNull()
    expect(parser.bomSkip(b('\xef1'))).toBeNull()
    parser.feed(b('1'), true)
    expect(parser.bomSkip(b('\xef\xbb\xbf'))).toBe(0)
  })

  it('counts the lines and columns of bytes it skips', () => {
    const parser = new JqParser()
    parser.skip(b('\xef\xbb\xbf[1]\n'), 3, 7)
    expect(parser.bomSkip(b('\xef\xbb\xbf'))).toBe(0)
    parser.feed(b('  ]'), false)
    expect(parser.next()).toEqual(new JqParseError("Unmatched ']' at line 2, column 3"))
  })

  it('reads on in the same column after a skip without a newline', () => {
    const parser = new JqParser()
    parser.skip(b('[1,2]'), 0, 5)
    parser.feed(b(' x'), false)
    expect(parser.next()).toEqual(
      new JqParseError('Invalid numeric literal at EOF at line 1, column 7'),
    )
  })
})

describe('numberValue', () => {
  const cases: readonly (readonly [string, number | typeof NO_VALUE])[] = [
    ['12', 12],
    ['+1', 1],
    ['007', 7],
    ['-0', -0],
    ['.5', 0.5],
    ['1.', 1],
    ['1.e5', 100000],
    ['-infinity', -Infinity],
    ['+Inf', Infinity],
    ['1e999', Infinity],
    ['NaN', NaN],
    ['-sNaN000', NaN],
    ['x', NO_VALUE],
    ['1e', NO_VALUE],
    ['nan1', NO_VALUE],
    ['0x1f', NO_VALUE],
    ['1_000', NO_VALUE],
    [' 1', NO_VALUE],
    ['\xb2', NO_VALUE],
    ['', NO_VALUE],
  ]
  for (const [literal, value] of cases) {
    it(`reads ${label(literal)}`, () => {
      expect(numberValue(literal)).toBe(value)
    })
  }
})

describe('decodeUtf8', () => {
  const cases: readonly (readonly [string, string])[] = [
    ['plain', 'plain'],
    ['\xf0\x80\x80\x80', FFFD],
    ['\xed\xa0\x80', FFFD],
    ['\xf4\x90\x80\x80', FFFD],
    ['\xe2\x82', FFFD],
    ['\xc0\x80', FFFD + FFFD],
    ['\xe2\x82x', `${FFFD}x`],
    ['\xe2a', FFFD],
    ['a\xffb', `a${FFFD}b`],
    ['\xc3\xa9\xff\xc3\xa9', `\xe9${FFFD}\xe9`],
    ['\xef\xbb\xbfa', `${BOM}a`],
    ['\xf0\x9f\x98\x80', String.fromCodePoint(0x1f600)],
  ]
  for (const [data, text] of cases) {
    it(`replaces each bad sequence of ${label(data)} once`, () => {
      expect(decodeUtf8(b(data))).toBe(text)
    })
  }
})

describe('utf8Missing', () => {
  const cases: readonly (readonly [string, number])[] = [
    ['a', 0],
    ['ab', 0],
    ['a\xe2', 2],
    ['a\xe2\x82', 1],
    ['a\xe2\x82\xac', 0],
    ['a\xf0\x9f', 2],
    ['a\x80', 0],
    ['a\xff', 0],
    ['\x80\x80', 0],
  ]
  for (const [piece, missing] of cases) {
    it(`says ${label(piece)} misses ${String(missing)}`, () => {
      expect(utf8Missing(b(piece))).toBe(missing)
    })
  }
})

// A differential run against jq-wasm, which is jq 1.8.2 built to WebAssembly
// reading the text as its input file: jq's own parser over the same bytes.
const ALPHABET: readonly string[] = [
  '{',
  '}',
  '[',
  ']',
  ':',
  ',',
  '"',
  '\\',
  ' ',
  '\n',
  '\t',
  '1',
  '0',
  '-',
  '+',
  '.',
  'e',
  'E',
  't',
  'r',
  'u',
  'n',
  'a',
  'f',
  'l',
  's',
  'x',
  '\x01',
  '\x00',
  '\xe9',
  '"a"',
  'true',
  'null',
  'false',
  '12',
  '"\\u00e9"',
  '"\\ud83d\\ude00"',
  '"\\ud800"',
  '"\\udc00"',
  '\\u',
  'nan',
  'NaN',
  'inf',
  '1e5',
  '.5',
  '"\\n"',
  '{"k":1}',
  '[1,2]',
  "'",
  BOM,
]
const SEQ_ALPHABET: readonly string[] = [...ALPHABET, '\x1e', '\x1e', '\x1e', '\x1e[1,2]\n']
const SEEDS: readonly string[] = [
  '{"a":1,"b":[1,2,{"c":null}]}',
  '[1,2,3]',
  '"str"',
  '123',
  'true',
  '{"a":{"b":{"c":[true,false]}}}',
  '[{"x":"y"},{"z":[]}]',
  '1 2 3',
  '{"a":1}\n{"b":2}\n',
  '[]',
  '{}',
  '[[[]]]',
  '-0.5e10',
  '"a\\"b"',
]
const SEQ_SEEDS: readonly string[] = [
  ...SEEDS.map((seed) => `\x1e${seed}\n`),
  '\x1e1\x1e2',
  '\x1e{"a":[1,2]}\n\x1e"x"\n',
  '\x1e[1,\x1e2\n',
]

const PARSE_ERROR = 'jq: parse error: '
const IGNORED_ERROR = 'jq: ignoring parse error: '

function mulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function randint(rng: () => number, low: number, high: number): number {
  return low + Math.floor(rng() * (high - low + 1))
}

function choice(rng: () => number, items: readonly string[]): string {
  const item = items[Math.floor(rng() * items.length)]
  if (item === undefined) throw new Error('nothing to choose from')
  return item
}

function mutant(rng: () => number, alphabet: readonly string[], seeds: readonly string[]): string {
  if (rng() < 0.5) {
    const parts: string[] = []
    for (let n = randint(rng, 0, 12); n > 0; n -= 1) parts.push(choice(rng, alphabet))
    return parts.join('')
  }
  const text = Array.from(choice(rng, seeds))
  for (let n = randint(rng, 0, 3); n > 0; n -= 1) {
    const at = randint(rng, 0, text.length)
    const roll = rng()
    if (roll < 0.33 && text.length > 0) {
      text.splice(Math.min(at, text.length - 1), 1)
    } else if (roll < 0.66) {
      text.splice(at, 0, choice(rng, alphabet))
    } else if (text.length > 0) {
      text[Math.min(at, text.length - 1)] = choice(rng, alphabet)
    }
  }
  return text.join('')
}

/** What one run of jq printed: its values, and the parse errors it reported. */
interface Run {
  readonly values: unknown[]
  readonly errors: string[]
}

function jqReads(jq: Jq, text: string, flags: readonly string[], seq: boolean): Run {
  const result = jq.raw(text, '.', ['-c', ...flags])
  const lines = result.stdout === '' ? [] : result.stdout.split('\n')
  const values = lines.map((line) => {
    if (seq && !line.startsWith('\x1e')) throw new Error(`no RS before ${line}`)
    return JSON.parse(seq ? line.slice(1) : line) as unknown
  })
  const reports = result.stderr === '' ? [] : result.stderr.split('\n')
  const prefix = seq ? IGNORED_ERROR : PARSE_ERROR
  const errors = reports.map((report) => {
    if (!report.startsWith(prefix)) throw new Error(`unexpected report: ${report}`)
    return report.slice(prefix.length)
  })
  const exit = errors.length > 0 && !seq ? 5 : 0
  if (result.exitCode !== exit) throw new Error(`unexpected exit: ${JSON.stringify(result)}`)
  return { values, errors }
}

function ours(got: readonly unknown[]): Run {
  return {
    values: got.filter((item) => !isErr(item)),
    errors: got.filter(isErr).map((item) => item.error),
  }
}

// jq prints NaN as null and an infinite number as the largest double, or
// as the literal it read (1E+1000), which JSON.parse reads back as infinite.
function loose(want: unknown, got: unknown): boolean {
  if (typeof got === 'number') {
    if (Number.isNaN(got)) return want === null
    if (typeof want !== 'number') return false
    if (!Number.isFinite(got)) {
      return Math.abs(want) >= Number.MAX_VALUE && Math.sign(want) === Math.sign(got)
    }
    return want === got
  }
  if (Array.isArray(got)) {
    return (
      Array.isArray(want) &&
      want.length === got.length &&
      got.every((item: unknown, i) => loose(want[i], item))
    )
  }
  if (typeof got === 'object' && got !== null) {
    if (typeof want !== 'object' || want === null || Array.isArray(want)) return false
    const keys = Object.keys(got)
    const wantKeys = Object.keys(want)
    return (
      keys.length === wantKeys.length &&
      keys.every(
        (key, i) =>
          wantKeys[i] === key &&
          loose((want as Record<string, unknown>)[key], (got as Record<string, unknown>)[key]),
      )
    )
  }
  return want === got
}

let jqInstance: Promise<Jq> | null = null

function jqWasm(): Promise<Jq> {
  jqInstance ??= loadJq()
  return jqInstance
}

describe('JqParser against jq-wasm', () => {
  const modes = [
    { name: 'plain', flags: [], seq: false, streaming: false, count: 2500, seed: 1325 },
    { name: '--stream', flags: ['--stream'], seq: false, streaming: true, count: 800, seed: 7 },
    { name: '--seq', flags: ['--seq'], seq: true, streaming: false, count: 800, seed: 11 },
    {
      name: '--seq --stream',
      flags: ['--seq', '--stream'],
      seq: true,
      streaming: true,
      count: 400,
      seed: 13,
    },
  ]
  for (const mode of modes) {
    it(`agrees with jq 1.8.2 ${mode.name} on generated input`, async () => {
      const jq = await jqWasm()
      const rng = mulberry32(mode.seed)
      const alphabet = mode.seq ? SEQ_ALPHABET : ALPHABET
      const seeds = mode.seq ? SEQ_SEEDS : SEEDS
      const misses: unknown[] = []
      for (let n = 0; n < mode.count; n += 1) {
        const text = mutant(rng, alphabet, seeds)
        const want = jqReads(jq, text, mode.flags, mode.seq)
        const data = ENC.encode(text)
        for (const read of READS) {
          const got = ours(read(data, mode.seq, mode.streaming))
          const same =
            got.errors.length === want.errors.length &&
            got.errors.every((message, i) => message === want.errors[i]) &&
            loose(want.values, got.values)
          if (!same && misses.length < 5) misses.push({ text, read: read.name, want, got })
        }
      }
      expect(misses).toEqual([])
    }, 60_000)
  }
})
