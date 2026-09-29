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

import { expect, it } from 'vitest'
import { mappedIdentity, parseMailmap } from './mailmap.ts'

it.each([
  ['Canonical <old@example.com>', 'Canonical <old@example.com>'],
  ['<new@example.com> <old@example.com>', 'Old <new@example.com>'],
  ['Canonical <new@example.com> <old@example.com>', 'Canonical <new@example.com>'],
  ['Canonical <new@example.com> Old <old@example.com>', 'Canonical <new@example.com>'],
  ['Canonical <new@example.com> Someone <old@example.com>', 'Old <old@example.com>'],
  ['# Canonical <old@example.com>\nbad line', 'Old <old@example.com>'],
  ['Canonical <OLD@EXAMPLE.COM>', 'Canonical <old@example.com>'],
])('maps identity form %s', (mapping, expected) => {
  expect(mappedIdentity('Old <old@example.com>', parseMailmap(mapping))).toBe(expected)
})

it('prefers a specific identity over a later email mapping', () => {
  const mapping = parseMailmap(
    'Specific <specific@example.com> Old <OLD@example.com>\nGeneric <generic@example.com> <old@example.com>\n',
  )
  expect(mappedIdentity('Old <old@example.com>', mapping)).toBe('Specific <specific@example.com>')
  expect(mappedIdentity('Another <old@example.com>', mapping)).toBe('Generic <generic@example.com>')
})

it('replaces the email entry whole with a specific one', () => {
  const mapping = parseMailmap(
    'Simple <old@example.com>\n<new@example.com> Old <old@example.com>\n',
  )
  expect(mappedIdentity('Old <old@example.com>', mapping)).toBe('Old <new@example.com>')
})

it('lets the last specific entry for a name win whole', () => {
  const mapping = parseMailmap(
    'First <first@example.com> Old <old@example.com>\n<last@example.com> Old <old@example.com>\n',
  )
  expect(mappedIdentity('Old <old@example.com>', mapping)).toBe('Old <last@example.com>')
})

it('lets later email entries override only what they spell', () => {
  const mapping = parseMailmap('Name <old@example.com>\n<new@example.com> <old@example.com>\n')
  expect(mappedIdentity('Old <old@example.com>', mapping)).toBe('Name <new@example.com>')
})

it('reads only a first-column hash as a comment', () => {
  const mapping = parseMailmap(' # Hashed <old@example.com>\n')
  expect(mappedIdentity('Old <old@example.com>', mapping)).toBe('# Hashed <old@example.com>')
})

it('matches an empty recorded email with an empty second email', () => {
  const mapping = parseMailmap('Named <named@example.com> Nobody <>\n')
  expect(mappedIdentity('Nobody <>', mapping)).toBe('Named <named@example.com>')
})
