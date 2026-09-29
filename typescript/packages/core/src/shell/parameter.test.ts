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

import { scanParameter } from './parameter.ts'

describe('scanParameter', () => {
  const cases: [string, string, string][] = [
    ['$10', '1', '0'],
    ['$123abc', '1', '23abc'],
    ['$49.99', '4', '9.99'],
    ['$00', '0', '0'],
    ['${10}x', '10', 'x'],
    ['${0012}x', '0012', 'x'],
    ['$name_12.x', 'name_12', '.x'],
    ['${name_12}.x', 'name_12', '.x'],
    ['$_x9-y', '_x9', '-y'],
    ['$a[0]', 'a', '[0]'],
    ['$nameé', 'name', 'é'],
    ['$1é', '1', 'é'],
    ['$@suffix', '@', 'suffix'],
    ['$*suffix', '*', 'suffix'],
    ['$#suffix', '#', 'suffix'],
    ['$?suffix', '?', 'suffix'],
    ['$$suffix', '$', 'suffix'],
    ['$!suffix', '!', 'suffix'],
    ['$-suffix', '-', 'suffix'],
    ['${@}suffix', '@', 'suffix'],
    ['${*}suffix', '*', 'suffix'],
    ['${#}suffix', '#', 'suffix'],
    ['${?}suffix', '?', 'suffix'],
    ['${$}suffix', '$', 'suffix'],
    ['${!}suffix', '!', 'suffix'],
    ['${-}suffix', '-', 'suffix'],
  ]
  for (const prefix of ['', 'é💡 ']) {
    it.each(cases)(`recognizes %s after ${JSON.stringify(prefix)}`, (reference, name, suffix) => {
      const source = prefix + reference
      const ref = scanParameter(source, prefix.length)
      expect(ref).not.toBeNull()
      expect(ref?.[0]).toBe(name)
      expect(source.slice(ref?.[1])).toBe(suffix)
    })
  }
  it.each([
    '$',
    '$.',
    '$é',
    '$١',
    '$(',
    '$((',
    "$'quoted'",
    '$"quoted"',
    '${}',
    '${name',
    '${12abc}',
    '${name:-x}',
    '${#name}',
    '${!name}',
    '${a[0]}',
    '${name/x/y}',
    'name',
  ])('leaves nonreferences and complex expansions %s to their caller', (reference) => {
    expect(scanParameter(reference, 0)).toBeNull()
  })
})
