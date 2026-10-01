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
import { ContentType, FileType, PathSpec } from '@struktoai/mirage-core/types'
import { makeFakeAccessor } from './_test_utils.ts'
import { attrsToFileStat, stat } from './stat.ts'

function spec(p: string): PathSpec {
  return PathSpec.fromStrPath(p)
}

describe('core/ssh/stat', () => {
  it('returns FileStat for an existing file', async () => {
    const accessor = makeFakeAccessor({
      files: new Map([['/a.txt', { data: new TextEncoder().encode('abc') }]]),
      dirs: new Map([['/', {}]]),
    })
    const s = await stat(accessor, spec('/a.txt'))
    expect(s.size).toBe(3)
    expect(s.name).toBe('a.txt')
  })

  it('returns DIRECTORY type for a directory', async () => {
    const accessor = makeFakeAccessor({
      files: new Map(),
      dirs: new Map([
        ['/', {}],
        ['/d', {}],
      ]),
    })
    const s = await stat(accessor, spec('/d'))
    expect(s.type).toBe(FileType.DIRECTORY)
    expect(s.size).toBeNull()
  })

  it('throws ENOENT for missing path', async () => {
    const accessor = makeFakeAccessor({
      files: new Map(),
      dirs: new Map([['/', {}]]),
    })
    await expect(stat(accessor, spec('/nope'))).rejects.toMatchObject({ code: 'ENOENT' })
  })
})

const FILE_MODE = 0o100644
const DIR_MODE = 0o040755

describe('attrsToFileStat', () => {
  it('returns DIRECTORY type for a directory mode', () => {
    const s = attrsToFileStat('mydir', { mode: DIR_MODE, size: 0 })
    expect(s.type).toBe(FileType.DIRECTORY)
    expect(s.name).toBe('mydir')
    expect(s.size).toBeNull()
  })

  it.each([
    ['foo.json', ContentType.JSON],
    ['foo.txt', ContentType.TEXT],
    ['foo.bin', ContentType.BINARY],
    ['weird-name.parquet', ContentType.BINARY],
  ])('types %s by its name', (name, content) => {
    const s = attrsToFileStat(name, { mode: FILE_MODE, size: 7 })
    expect(s.name).toBe(name)
    expect(s.content).toBe(content)
  })

  it('formats modified as ISO 8601 and fingerprints by it', () => {
    const s = attrsToFileStat('foo.txt', { mode: FILE_MODE, mtime: 0 })
    expect(s.modified).toBe('1970-01-01T00:00:00Z')
    expect(s.fingerprint).toBe(s.modified)
    expect(attrsToFileStat('foo.txt', { mode: FILE_MODE, mtime: 1 }).fingerprint).not.toBe(
      s.fingerprint,
    )
    const d = attrsToFileStat('mydir', { mode: DIR_MODE, mtime: 0 })
    expect(d.fingerprint).toBe(d.modified)
  })

  it('leaves modified and fingerprint null when mtime is omitted', () => {
    const s = attrsToFileStat('foo.txt', { mode: FILE_MODE })
    expect(s.modified).toBeNull()
    expect(s.fingerprint).toBeNull()
    expect(attrsToFileStat('mydir', { mode: DIR_MODE }).fingerprint).toBeNull()
  })
})
