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
import {
  headRef,
  isRootRef,
  knownNames,
  matchAsPath,
  matchShort,
  refKind,
  resolveRef,
} from './ref_list.ts'
import { RefKind } from './types.ts'

const SHA = '1'.repeat(40)
const TABLE = new Map([
  ['HEAD', 'ref: refs/heads/main'],
  ['refs/heads/main', SHA],
  ['refs/remotes/origin/HEAD', 'ref: refs/remotes/origin/main'],
  ['refs/remotes/origin/main', SHA],
  ['refs/remotes/origin/dangling', 'ref: refs/remotes/origin/gone'],
])

it.each([
  [[], true],
  [['refs/heads/feat/git'], true],
  [['refs/heads'], true],
  [['refs/heads/'], true],
  [['refs/hea'], false],
  [['refs/*'], false],
  [['refs/*/*'], false],
  [['refs/*/*/*'], true],
  [['refs/**'], true],
  [['**/git'], true],
  [['refs/heads/feat/g?t'], true],
  [['refs/tags', 'refs/heads/*/git'], true],
])('selects by prefix or path glob with %j', (patterns, expected) => {
  expect(matchAsPath('refs/heads/feat/git', patterns)).toBe(expected)
})

it('keeps the prefix rule case-sensitive under ignore-case', () => {
  expect(matchAsPath('refs/heads/Main', ['refs/heads/m*'], true)).toBe(true)
  expect(matchAsPath('refs/heads/Main', ['refs/HEADS'], true)).toBe(false)
})

it.each([
  ['refs/tags/v1.0', ['v1*'], false, true],
  ['refs/remotes/origin/main', ['origin/*'], false, true],
  ['refs/heads/feat/x', ['feat*'], false, true],
  ['refs/heads/Upper', ['u*'], false, false],
  ['refs/heads/Upper', ['u*'], true, true],
  ['HEAD', ['ma*'], false, false],
  ['refs/tags/v1.0', [], false, true],
])('matches %s past its namespace with %j', (name, patterns, icase, expected) => {
  expect(matchShort(name, patterns, icase)).toBe(expected)
})

it('resolves a symbolic ref through its target', () => {
  expect(resolveRef(TABLE, 'refs/remotes/origin/HEAD')).toEqual([SHA, 'refs/remotes/origin/main'])
  expect(resolveRef(TABLE, 'refs/remotes/origin/dangling')).toEqual([
    null,
    'refs/remotes/origin/gone',
  ])
  expect(resolveRef(TABLE, 'refs/heads/main')).toEqual([SHA, null])
  expect(headRef(TABLE)).toBe('refs/heads/main')
  expect(headRef(new Map([['HEAD', SHA]]))).toBe('HEAD')
  expect(headRef(new Map([['HEAD', 'ref: refs/heads/unborn']]))).toBeNull()
})

it('knows what resolves plus the root refs', () => {
  const known = knownNames(TABLE, ['HEAD', 'ORIG_HEAD', 'config', 'packed-refs'])
  expect(known.has('refs/remotes/origin/dangling')).toBe(false)
  for (const name of ['HEAD', 'ORIG_HEAD', 'refs/heads/main']) expect(known.has(name)).toBe(true)
  expect(known.has('config')).toBe(false)
})

it.each([
  ['HEAD', true],
  ['ORIG_HEAD', true],
  ['AUTO_MERGE', true],
  ['FETCH_HEAD', false],
  ['MERGE_HEAD', false],
  ['config', false],
  ['NOT_A_ROOT', false],
])('reads %s as a root ref: %s', (name, expected) => {
  expect(isRootRef(name)).toBe(expected)
})

it.each([
  ['refs/heads/x', RefKind.BRANCH],
  ['refs/remotes/o/x', RefKind.REMOTE],
  ['refs/tags/x', RefKind.TAG],
  ['HEAD', RefKind.DETACHED],
  ['ORIG_HEAD', RefKind.ROOT],
  ['refs/notes/commits', RefKind.OTHER],
])('takes the kind of %s from its name', (name, kind) => {
  expect(refKind(name)).toBe(kind)
})
