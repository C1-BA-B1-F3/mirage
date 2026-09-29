import { expect, it } from 'vitest'
import type { JsonValue } from '../../../../types.ts'
import { renderTemplate } from './template.ts'

const ROWS: JsonValue = [
  { title: 'a', number: 1 },
  { title: 'b', number: 2 },
]

const cases: [string, JsonValue, string][] = [
  [
    '{{range .}}{{if .ok}}{{.name}}{{else}}skip{{end}};{{end}}',
    [
      { ok: true, name: '雪' },
      { ok: false, name: 'x' },
    ],
    '雪;skip;',
  ],
  ['{{range .}}x{{else}}empty{{end}}', [], 'empty'],
  ['{{pluck "name" . | join ", "}}', [{ name: 'one' }, { name: 'two' }], 'one, two'],
  [
    '{{printf "%q %v %f" .name .ok .value}}',
    { name: '雪', ok: true, value: 1.5 },
    '"雪" true 1.500000',
  ],
  ['  {{- with .item -}}{{.name}}{{end}}  ', { item: { name: 'one' } }, 'one  '],
  ['{{range $i, $issue := .}}{{$i}}:{{$issue.title}};{{end}}', ROWS, '0:a;1:b;'],
  ['{{range $issue := .}}{{$issue.number}}{{end}}', ROWS, '12'],
  ['{{range $k, $v := index . 0}}{{$k}}={{$v}} {{end}}', ROWS, 'number=1 title=a '],
  ['{{with $x := index . 0}}{{$x.title}}/{{.number}}{{end}}', ROWS, 'a/1'],
  ['{{if $t := len .}}{{$t}}{{else}}none{{end}}', ROWS, '2'],
  ['{{$n := len .}}{{range .}}{{.title}}{{$n}}{{end}}', ROWS, 'a2b2'],
  ['{{$n := 0}}{{range .}}{{$n = .number}}{{end}}{{$n}}', ROWS, '2'],
]

it.each(cases)('renders %s', (template, value, expected) => {
  expect(renderTemplate(template, value)).toBe(expected)
})

it('rejects unclosed blocks', () => {
  expect(() => renderTemplate('{{range .}}', [])).toThrow('unexpected EOF')
})

it.each([
  ['{{$nope}}', 'undefined variable "$nope"'],
  ['{{$nope = 1}}', 'undefined variable "$nope"'],
  ['{{if $a, $b := .}}x{{end}}', 'too many declarations in if'],
])('rejects %s', (template, message) => {
  expect(() => renderTemplate(template, ROWS)).toThrow(message)
})
