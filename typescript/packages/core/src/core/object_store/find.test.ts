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
import { FakeAccessor, FakeStore, makeDriver, spec } from './fakes.ts'
import { makeFind } from './find.ts'

const accessor = new FakeAccessor()

describe('object_store find', () => {
  it('synthesizes the implicit parent chain', async () => {
    const store = new FakeStore({ 'data/a/b/deep.txt': 'x' })
    const find = makeFind(makeDriver(store))
    await expect(find(accessor, spec('/data'), { type: 'd' })).resolves.toEqual([
      '/data',
      '/data/a',
      '/data/a/b',
    ])
  })

  it('-type f drops synthesized dirs', async () => {
    const store = new FakeStore({ 'data/a/b.txt': 'x' })
    const find = makeFind(makeDriver(store))
    await expect(find(accessor, spec('/data'), { type: 'f' })).resolves.toEqual(['/data/a/b.txt'])
  })

  it('a marker-only start is empty', async () => {
    const store = new FakeStore({ 'data/': '' })
    const find = makeFind(makeDriver(store))
    await expect(find(accessor, spec('/data'), { empty: true })).resolves.toEqual(['/data'])
  })

  it('a missing start emits nothing', async () => {
    const find = makeFind(makeDriver(new FakeStore()))
    await expect(find(accessor, spec('/never'))).resolves.toEqual([])
  })

  it('a narrowed query still emits the start path', async () => {
    // The pushed-down -name query matches nothing, but the prefix holds
    // keys, so the probe restores the start directory.
    const store = new FakeStore({ 'data/a.txt': 'x' })
    const find = makeFind(makeDriver(store, true))
    await expect(find(accessor, spec('/data'), { name: '*.md', type: 'f' })).resolves.toEqual([])
    await expect(find(accessor, spec('/data'), { name: '*.txt', type: 'f' })).resolves.toEqual([
      '/data/a.txt',
    ])
  })

  it('the size gate counts a directory as DIR_SIZE bytes', async () => {
    const store = new FakeStore({ 'data/a/big.txt': '123456' })
    const find = makeFind(makeDriver(store))
    await expect(find(accessor, spec('/data'), { minSize: 1 })).resolves.toEqual([
      '/data',
      '/data/a',
      '/data/a/big.txt',
    ])
    await expect(find(accessor, spec('/data'), { maxSize: 100 })).resolves.toEqual([
      '/data/a/big.txt',
    ])
  })
})
