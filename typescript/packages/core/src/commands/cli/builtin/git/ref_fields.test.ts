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
import { GitError, UnknownDateFormatError, UnsupportedFieldError } from './errors.ts'
import {
  abbreviationRequests,
  cInt,
  cUint,
  fieldValue,
  lstripRef,
  messageParts,
  parseField,
  rstripRef,
  shortenRef,
} from './ref_fields.ts'
import {
  DateKind,
  FieldCompare,
  RefKind,
  type RefContext,
  type RefItem,
  type RefObject,
  type RefUpstream,
} from './types.ts'

const ENC = new TextEncoder()
const COMMIT: RefObject = {
  oid: 'c'.repeat(40),
  type: 'commit',
  raw: ENC.encode(
    `tree ${'t'.repeat(40)}\nparent ${'p'.repeat(40)}\n` +
      'author A U Thor <author@example.com> 1584244800 +0530\n' +
      'committer C O Mitter <committer@example.com> 1584381600 -0800\n' +
      '\nSubject line\nwraps\n\nBody one.\nBody two.\n',
  ),
}
const TAG: RefObject = {
  oid: 'a'.repeat(40),
  type: 'tag',
  raw: ENC.encode(
    `object ${'c'.repeat(40)}\ntype commit\ntag v1\n` +
      'tagger T Agger <tagger@example.com> 1600000000 +0000\n\n' +
      'Release notes\n\nMore.\n-----BEGIN PGP SIGNATURE-----\nsig\n' +
      '-----END PGP SIGNATURE-----\n',
  ),
}
const BLOB: RefObject = { oid: 'b'.repeat(40), type: 'blob', raw: ENC.encode('data\n') }
const CTX: RefContext = {
  known: new Set(['refs/heads/main', 'refs/tags/main']),
  strict: true,
  head: 'refs/heads/main',
  headDescription: '',
  abbrev: 7,
  abbreviations: new Map(),
  mailmap: [],
  date: { kind: DateKind.NORMAL, local: false, strftime: '', now: 1700000000, zone: null },
  suffixes: [],
}

it.each([
  ['objectname', COMMIT.oid],
  ['*objectname', COMMIT.oid],
  ['tree', 't'.repeat(40)],
  ['parent', 'p'.repeat(40)],
])('widens collisions for %s but keeps longer requested widths', (name, oid) => {
  const row = item(name.startsWith('*') ? TAG : COMMIT, 'refs/tags/v1', { peeled: COMMIT })
  const ctx = { ...CTX, abbreviations: new Map([[oid, 8]]) }
  for (const [suffix, width] of [
    ['', 40],
    [':short', 8],
    [':short=4', 8],
    [':short=12', 12],
  ] as const)
    expect(fieldValue(parseField(name + suffix), row, ctx).text).toBe(oid.slice(0, width))
})

it('deduplicates abbreviation requests at the smallest width', () => {
  const row = item(TAG, 'refs/tags/v1', { peeled: COMMIT })
  const fields = [
    'refname:short',
    'objectname',
    '*objectname:short=12',
    '*objectname:short',
    '*objectname:short=4',
    '*parent:short',
    '*tree:short=40',
  ].map(parseField)
  expect(abbreviationRequests(fields, [row, row], CTX)).toEqual(
    new Map([
      [COMMIT.oid, 4],
      ['p'.repeat(40), 7],
      ['t'.repeat(40), 40],
    ]),
  )
})

function item(
  obj: RefObject | null,
  name = 'refs/heads/main',
  extra: Partial<RefItem> = {},
): RefItem {
  return {
    name,
    oid: obj?.oid ?? '0'.repeat(40),
    kind: RefKind.BRANCH,
    symref: null,
    obj,
    peeled: null,
    upstream: null,
    worktree: '',
    ...extra,
  }
}

function value(
  name: string,
  obj: RefObject | null = COMMIT,
  ref = 'refs/heads/main',
  extra: Partial<RefItem> = {},
): string {
  return fieldValue(parseField(name), item(obj, ref, extra), CTX).text
}

it.each([
  ['2', 2],
  [' +3', 3],
  ['-4', -4],
  ['', null],
  ['2 ', null],
  ['x', null],
  ['99999999999', null],
])('reads %j as strtol_i', (text, expected) => {
  expect(cInt(text)).toBe(expected)
})

it.each([
  ['7', 7],
  ['+7', 7],
  ['-7', null],
  ['0', 0],
  ['7x', null],
])('reads %j as strtoul_ui', (text, expected) => {
  expect(cUint(text)).toBe(expected)
})

it.each([
  ['', 'malformed field name: '],
  ['*', 'malformed field name: *'],
  ['bogus', 'unknown field name: bogus'],
  ['refnamex', 'unknown field name: refnamex'],
  ['refname:bogus', 'unrecognized %(refname) argument: bogus'],
  ['*refname:bogus', 'unrecognized %(*refname) argument: bogus'],
  ['refname:lstrip=x', 'Integer value expected refname:lstrip=x'],
  ['symref:strip=x', 'Integer value expected refname:lstrip=x'],
  ['refname:rstrip=', 'Integer value expected refname:rstrip='],
  ['objectname:short=0', "positive value expected '0' in %(objectname:short=0)"],
  ['objectname:long', 'unrecognized %(objectname) argument: long'],
  ['*objecttype:x', '%(objecttype) does not take arguments'],
  ['contents:lines=-1', 'positive value expected contents:lines=-1'],
  ['authoremail:trimfoo', 'unrecognized %(authoremail) argument: foo'],
  ['authoremail:trim,', 'unrecognized %(authoremail) argument: '],
  ['align', 'expected format: %(align:<width>,<position>)'],
  ['align:left', 'positive width expected with the %(align) atom'],
  ['align:position=up,5', 'unrecognized position:up'],
  ['if:x', 'unrecognized %(if) argument: x'],
  ['upstream:short,track', 'unrecognized %(upstream) argument: short,track'],
])('refuses the field %j in git words', (name, message) => {
  expect(() => parseField(name)).toThrow(GitError)
  expect(() => parseField(name)).toThrow(message)
})

it.each([
  'describe',
  'trailers',
  'contents:trailers',
  'signature:key',
  'push',
  'color:red',
  'objectsize:disk',
  'ahead-behind:main',
  'flag',
])('calls %s unsupported, not unknown', (name) => {
  expect(() => parseField(name)).toThrow(UnsupportedFieldError)
  expect(() => parseField(name)).toThrow(`unsupported field name: ${name} `)
})

it('compares a date with a style as text', () => {
  expect(parseField('committerdate').compare).toBe(FieldCompare.TIME)
  expect(parseField('committerdate:iso').compare).toBe(FieldCompare.TEXT)
  expect(parseField('contents:size').compare).toBe(FieldCompare.NUMBER)
})

describe('shortenRef', () => {
  const known = new Set(['HEAD', 'refs/heads/main', 'refs/tags/main'])
  it.each([
    ['refs/heads/main', 'heads/main'],
    ['refs/tags/main', 'tags/main'],
    ['refs/remotes/origin/HEAD', 'origin'],
    ['refs/remotes/origin/main', 'origin/main'],
    ['refs/notes/commits', 'notes/commits'],
    ['refs/heads/HEAD', 'heads/HEAD'],
    ['HEAD', 'HEAD'],
  ])('shortens %s to what still names it', (name, expected) => {
    expect(shortenRef(name, known)).toBe(expected)
  })

  it('ignores later rules when loose', () => {
    const both = new Set(['refs/heads/main', 'refs/tags/main'])
    expect(shortenRef('refs/tags/main', both, false)).toBe('main')
    expect(shortenRef('refs/heads/main', both, false)).toBe('heads/main')
  })
})

it.each([
  [0, 'refs/heads/feat/x', 'refs/heads/feat/x'],
  [1, 'heads/feat/x', 'refs/heads/feat'],
  [2, 'feat/x', 'refs/heads'],
  [4, '', ''],
  [-1, 'x', 'refs'],
  [-3, 'heads/feat/x', 'refs/heads/feat'],
  [-9, 'refs/heads/feat/x', 'refs/heads/feat/x'],
])('strips %i components from either end', (count, left, right) => {
  expect(lstripRef('refs/heads/feat/x', count)).toBe(left)
  expect(rstripRef('refs/heads/feat/x', count)).toBe(right)
})

it('splits a message into subject, body and signature', () => {
  const [message, subject, body, sig] = messageParts(new TextDecoder().decode(TAG.raw))
  expect(subject).toBe('Release notes')
  expect(message.slice(body, sig)).toBe('More.\n')
  expect(message.slice(sig).startsWith('-----BEGIN PGP SIGNATURE-----')).toBe(true)
})

it.each([
  ['subject', 'Subject line wraps'],
  ['subject:sanitize', 'Subject-line-wraps'],
  ['body', 'Body one.\nBody two.\n'],
  ['contents:lines=2', 'Subject line\n    wraps'],
  ['contents:size', '40'],
  ['author', 'A U Thor <author@example.com> 1584244800 +0530'],
  ['authorname', 'A U Thor'],
  ['authoremail', '<author@example.com>'],
  ['authoremail:trim', 'author@example.com'],
  ['authoremail:localpart', 'author'],
  ['authordate', 'Sun Mar 15 09:30:00 2020 +0530'],
  ['authordate:short', '2020-03-15'],
  ['committerdate:unix', '1584381600'],
  ['creator', 'C O Mitter <committer@example.com> 1584381600 -0800'],
  ['author:foo', ''],
  ['tree:short', 'ttttttt'],
  ['parent:short=4', 'pppp'],
  ['numparent', '1'],
  ['tagger', ''],
  ['objectsize', String(COMMIT.raw.length)],
  ['*objectname', ''],
  ['*refname', 'refs/heads/main^{}'],
  ['*symref', '^{}'],
  ['HEAD', '*'],
  ['refname:short', 'heads/main'],
])('reads the commit field %s', (name, expected) => {
  expect(value(name)).toBe(expected)
})

it.each([
  ['tag', 'v1'],
  ['type', 'commit'],
  ['object', 'c'.repeat(40)],
  ['taggername', 'T Agger'],
  ['creatordate:iso', '2020-09-13 12:26:40 +0000'],
  ['contents:body', 'More.\n'],
  ['contents:signature', '-----BEGIN PGP SIGNATURE-----\nsig\n-----END PGP SIGNATURE-----\n'],
  ['authorname', ''],
  ['*objectname', 'c'.repeat(40)],
  ['*subject', 'Subject line wraps'],
  ['*authorname', 'A U Thor'],
])('reads the tag field %s and what it peels to', (name, expected) => {
  expect(value(name, TAG, 'refs/tags/v1', { peeled: COMMIT })).toBe(expected)
})

it('refuses a bad date style only where the date is', () => {
  expect(value('authordate:bogus', BLOB)).toBe('')
  expect(value('authordate:bogus', TAG, 'refs/tags/v1')).toBe('')
  expect(() => value('authordate:bogus')).toThrow(UnknownDateFormatError)
})

it('maps the ident under the mailmap options', () => {
  const ctx: RefContext = {
    ...CTX,
    mailmap: [{ email: 'author@example.com', name: null, mappedName: 'Alice', mappedEmail: null }],
  }
  const it_ = item(COMMIT, 'refs/heads/x')
  expect(fieldValue(parseField('authorname:mailmap'), it_, ctx).text).toBe('Alice')
  expect(fieldValue(parseField('authoremail:mailmap,trim'), it_, ctx).text).toBe(
    'author@example.com',
  )
})

describe('upstream fields', () => {
  const up: RefUpstream = {
    ref: 'refs/remotes/origin/main',
    remote: 'origin',
    merge: 'refs/heads/main',
    ahead: 1,
    behind: 2,
    gone: false,
  }
  it.each([
    ['upstream', 'refs/remotes/origin/main'],
    ['upstream:short', 'origin/main'],
    ['upstream:lstrip=-1', 'main'],
    ['upstream:track', '[ahead 1, behind 2]'],
    ['upstream:track,nobracket', 'ahead 1, behind 2'],
    ['upstream:trackshort', '<>'],
    ['upstream:remotename', 'origin'],
    ['upstream:remoteref', 'refs/heads/main'],
  ])('reads %s', (name, expected) => {
    expect(value(name, COMMIT, 'refs/heads/main', { upstream: up })).toBe(expected)
    expect(value(name, COMMIT, 'refs/tags/main', { upstream: up })).toBe('')
  })

  it('tracks a gone upstream as gone', () => {
    const gone = { ...up, gone: true, ahead: 0, behind: 0 }
    expect(value('upstream:track', COMMIT, 'refs/heads/main', { upstream: gone })).toBe('[gone]')
    expect(value('upstream:trackshort', COMMIT, 'refs/heads/main', { upstream: gone })).toBe('')
  })
})
