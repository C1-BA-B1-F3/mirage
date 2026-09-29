import { expect, it } from 'vitest'
import { mappedIdentity, parseMailmap } from './mailmap.ts'

it.each([
  ['Canonical <old@example.com>', 'Canonical <old@example.com>'],
  ['<new@example.com> <old@example.com>', 'Old <new@example.com>'],
  ['Canonical <new@example.com> <old@example.com>', 'Canonical <new@example.com>'],
  ['Canonical <new@example.com> Old <old@example.com>', 'Canonical <new@example.com>'],
  ['Canonical <new@example.com> Someone <old@example.com>', 'Old <old@example.com>'],
  ['# Canonical <old@example.com>\nbad line', 'Old <old@example.com>'],
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
