import { expect, it } from 'vitest'
import { expandTableLong } from './compile.ts'
import { GNU_LONG_OPTIONS } from './long_options.ts'

it.each([
  ['grep', '--co', ['--context', '--color', '--colour', '--count']],
  ['date', '--u', ['--uct']],
  ['date', '--rfc', ['--rfc-email', '--rfc-3339']],
  ['gzip', '--s', ['--stdout', '--silent', '--synchronous', '--suffix']],
  ['cmp', '--print', ['--print-bytes', '--print-chars']],
  ['cat', '--number', ['--number']],
  ['date', '--universal', ['--uct']],
])('GNU %s %s option identity and ambiguity', (command, spelling, expected) => {
  expect(expandTableLong(GNU_LONG_OPTIONS[command] ?? [], spelling)).toEqual(expected)
})
