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
import {
  compactJsonBytes,
  compactJsonText,
  jsonBytes,
  jsonlBytes,
  jsonText,
  numberText,
  valueText,
} from './json.ts'

const DEC = new TextDecoder()

// Byte-for-byte the fixture in the python twin (tests/core/render/test_json.py).
// Both languages pin the same expected strings, so a change to either renderer
// breaks one of the two.
const PAYLOAD = {
  name: 'café 中文',
  tags: ['a', 'b'],
  meta: { n: 1, ok: true, none: null },
  empty: {},
}

const INDENTED = `{
  "name": "café 中文",
  "tags": [
    "a",
    "b"
  ],
  "meta": {
    "n": 1,
    "ok": true,
    "none": null
  },
  "empty": {}
}`

const COMPACT =
  '{"name":"café 中文","tags":["a","b"],"meta":{"n":1,"ok":true,"none":null},"empty":{}}'

describe('json render kit', () => {
  it('indents two and keeps non-ascii', () => {
    expect(DEC.decode(jsonBytes(PAYLOAD))).toBe(INDENTED)
  })

  it('renders indented text', () => {
    expect(jsonText(PAYLOAD)).toBe(INDENTED)
  })

  it('renders compact text with no separator padding', () => {
    expect(compactJsonText(PAYLOAD)).toBe(COMPACT)
  })

  it('encodes the compact text', () => {
    expect(DEC.decode(compactJsonBytes(PAYLOAD))).toBe(COMPACT)
  })

  it('terminates every jsonl row', () => {
    expect(DEC.decode(jsonlBytes([{ a: 1 }, { b: 2 }]))).toBe('{"a":1}\n{"b":2}\n')
  })

  it('renders no rows as empty', () => {
    expect(jsonlBytes([])).toEqual(new Uint8Array())
  })

  it('keeps the given jsonl order', () => {
    expect(DEC.decode(jsonlBytes([{ i: 2 }, { i: 1 }]))).toBe('{"i":2}\n{"i":1}\n')
  })
})

describe('valueText', () => {
  it('spells a value as its JSON does', () => {
    // A string is itself; anything else is its compact JSON, so a boolean
    // is `true` in both languages rather than Python's `True`, and an
    // integral float is the integer this side never told apart.
    expect(valueText('x')).toBe('x')
    expect(valueText('True')).toBe('True')
    expect(valueText(true)).toBe('true')
    expect(valueText(false)).toBe('false')
    expect(valueText(7)).toBe('7')
    expect(valueText(1.0)).toBe('1')
    expect(valueText(1.5)).toBe('1.5')
    expect(valueText(null)).toBe('null')
    expect(valueText({ a: 1.0, b: [true, null] })).toBe('{"a":1,"b":[true,null]}')
  })

  it('spells a float the way python does', () => {
    // A label holding 1e-7 spelled 1e-07 in python and 1e-7 here, so one
    // point had two paths; a nested number spells the same way.
    expect(valueText(1e-7)).toBe('1e-7')
    expect(valueText(1e21)).toBe('1e+21')
    expect(valueText({ a: 1e-7, b: [1e21] })).toBe('{"a":1e-7,"b":[1e+21]}')
  })
})

describe('numberText', () => {
  it('lays a float out as ECMAScript does', () => {
    // String() is the spec here; the python twin reproduces this table from
    // repr, whose digits agree and whose layout does not.
    expect(numberText(1e-7)).toBe('1e-7')
    expect(numberText(0.00001)).toBe('0.00001')
    expect(numberText(1.5e-5)).toBe('0.000015')
    expect(numberText(1e16)).toBe('10000000000000000')
    expect(numberText(1e21)).toBe('1e+21')
    expect(numberText(1.5e22)).toBe('1.5e+22')
    expect(numberText(123.0)).toBe('123')
    expect(numberText(-0)).toBe('0')
    expect(numberText(-1e-7)).toBe('-1e-7')
    expect(numberText(0.30000000000000004)).toBe('0.30000000000000004')
    expect(numberText(Number.NaN)).toBe('null')
    expect(numberText(Number.POSITIVE_INFINITY)).toBe('null')
  })
})

it('uses ECMAScript number spelling inside nested JSONL cells', () => {
  const rows = [{ cells: [1e-5, 1e-7, 1e20, 1e21, 1.0, -0.0, { number: -1.5e-5 }] }]
  expect(DEC.decode(jsonlBytes(rows))).toBe(
    '{"cells":[0.00001,1e-7,100000000000000000000,1e+21,1,0,{"number":-0.000015}]}\n',
  )
})
