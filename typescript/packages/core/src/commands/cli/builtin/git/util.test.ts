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

import { BadConfigValueError } from './errors.ts'
import { gitBool } from './util.ts'

describe('gitBool', () => {
  it.each([
    'true',
    'YES',
    'On',
    '1',
    '-1',
    '+1',
    '0x10',
    '010',
    '2k',
    '1g',
    ' 1',
    '-2097152k',
    '2147483647',
    '-2147483648',
  ])('reads %j as true', (value) => {
    expect(gitBool([value], 'core.bare', false)).toBe(true)
  })

  it.each(['false', 'No', 'OFF', '', '0', '-0'])('reads %j as false', (value) => {
    expect(gitBool([value], 'core.bare', true)).toBe(false)
  })

  // Pinned against git 2.54: strtoimax in base 0, one k, m or g, and a product
  // that has to fit an int.
  it.each([
    'maybe',
    ' true',
    '08',
    '0x',
    '1x',
    '1 ',
    '- 1',
    '2g',
    '2097152k',
    '2147483648',
    '-2147483649',
    '99999999999',
  ])('cannot read %j', (value) => {
    const read = (): boolean => gitBool([value], 'core.bare', false)
    expect(read).toThrow(BadConfigValueError)
    expect(read).toThrow(`bad boolean config value '${value}' for 'core.bare'`)
  })

  it('lets the last occurrence win', () => {
    expect(gitBool(['true', 'false'], 'core.bare', true)).toBe(false)
    expect(gitBool([], 'core.bare', true)).toBe(true)
  })

  it('parses every occurrence', () => {
    expect(() => gitBool(['maybe', 'true'], 'core.bare', false)).toThrow(BadConfigValueError)
  })
})
