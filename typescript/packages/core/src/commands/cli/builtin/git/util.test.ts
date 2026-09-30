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
import { configSection, gitBool, withoutSection } from './util.ts'
import { walk } from '../../walk.ts'
import { GIT } from './index.ts'

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

it('lands a later relative -C under the one before it', () => {
  const result = walk('git', GIT, ['-C', '/repo', '-C', 'docs', 'status'], '/')
  expect(result.groupFlags['-C']).toBe('/repo/docs')
})

describe('configSection', () => {
  it('escapes its name and quotes a value holding a comment start', () => {
    expect(
      configSection('branch', 'q"x', [
        ['remote', 'origin'],
        ['merge', 'refs/heads/we#rd'],
        ['note', ' pad\tend '],
      ]),
    ).toBe(
      '[branch "q\\"x"]\n\tremote = origin\n\tmerge = "refs/heads/we#rd"\n\tnote = " pad\\tend "\n',
    )
  })
})

describe('withoutSection', () => {
  const text =
    '[core]\n\tbare = false\n[branch "topic"]\n\tremote = o\n[branch "main"]\n\tremote = o\n' +
    '[Branch "topic"]\n\tmerge = m\n[branch "q\\"x"]\n\tremote = o\n'

  it('drops every block of that name only', () => {
    expect(withoutSection(text, 'branch', 'topic')).toBe(
      '[core]\n\tbare = false\n[branch "main"]\n\tremote = o\n[branch "q\\"x"]\n\tremote = o\n',
    )
    expect(withoutSection(text, 'branch', 'q"x').endsWith('[Branch "topic"]\n\tmerge = m\n')).toBe(
      true,
    )
  })
})
