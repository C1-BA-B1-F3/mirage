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

import { ContentType, PathSpec } from '../../types.ts'
import { stripSlash } from '../../utils/slash.ts'
import { Codec, PATH_SAFE } from '../hierarchy/codec.ts'
import { INVALID, ROOT, makeDetectScope, type ScopeMatch } from '../hierarchy/scope.ts'
import { blobLeaf, filtersOf, rowScopes, tableOf } from './scope.ts'
import type { Leaf } from './types.ts'

const GROUP_BY = ['label', 'kind']
const LEAVES: Leaf[] = [
  ['row_text', new Codec({ suffix: '.txt' }), ContentType.TEXT],
  blobLeaf('png'),
]

function match(pinned: string | null, groups: number, path: string): ScopeMatch {
  const detect = makeDetectScope(
    rowScopes(
      pinned !== null,
      Array.from({ length: groups }, () => PATH_SAFE),
      LEAVES,
    ),
  )
  return detect(new PathSpec({ vfsPath: stripSlash(path), virtual: path, directory: path }))
}

describe('row scopes', () => {
  const cat = { label: 'cat' }
  const catBig = { label: 'cat', kind: 'big' }
  it.each([
    [null, 2, '/', ROOT, null, {}],
    [null, 2, '/animals', 'group', 'animals', {}],
    [null, 2, '/animals/cat', 'group', 'animals', cat],
    [null, 2, '/animals/cat/big', 'group', 'animals', catBig],
    [null, 2, '/animals/cat/big/3.txt', 'row_text', 'animals', catBig],
    [null, 2, '/animals/cat/big/3.png', 'row_blob', 'animals', catBig],
    [null, 2, '/animals/cat/big/3.txt/extra', INVALID, null, {}],
    ['animals', 2, '/cat/big', 'group', 'animals', catBig],
    ['animals', 0, '/', ROOT, null, {}],
    ['animals', 0, '/3.txt', 'row_text', 'animals', {}],
    ['animals', 0, '/whatever', INVALID, null, {}],
  ])('pinned %s, %i groups: %s is %s', (pinned, groups, path, kind, table, filters) => {
    const m = match(pinned, groups, path)
    expect(m.kind).toBe(kind)
    if (table !== null) expect(tableOf(pinned, m)).toBe(table)
    expect(filtersOf(GROUP_BY, m)).toEqual(filters)
  })

  it.each([
    ['a∕b', 'a/b'],
    ['a⁄∕b', 'a∕b'],
    ['⁄', ''],
    ['⁄.env', '.env'],
  ])('decodes the group segment %s back to %j', (segment, value) => {
    expect(filtersOf(['label'], match('animals', 1, `/${segment}`))).toEqual({ label: value })
  })

  it('types a blob leaf by its extension', () => {
    const m = match('animals', 0, '/3.png')
    expect(m.slots.row_id).toBe('3')
    expect(m.scope?.filetype).toBe(ContentType.IMAGE_PNG)
  })
})
