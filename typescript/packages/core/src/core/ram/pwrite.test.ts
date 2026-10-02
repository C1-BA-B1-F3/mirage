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
import { RAMAccessor } from '../../accessor/ram.ts'
import { RAMStore } from '../../vfs/ram/store.ts'
import { PathSpec } from '../../types.ts'
import { pwrite } from './pwrite.ts'

const ENC = new TextEncoder()
const PATH = new PathSpec({ virtual: '/f.txt', directory: '/', vfsPath: 'f.txt' })

describe('pwrite', () => {
  it('keeps the bytes outside the window', async () => {
    const accessor = new RAMAccessor(new RAMStore())
    accessor.store.files.set('/f.txt', ENC.encode('hello'))
    await pwrite(accessor, PATH, ENC.encode('XY'), 1)
    expect(accessor.store.files.get('/f.txt')).toEqual(ENC.encode('hXYlo'))
    expect(accessor.store.modified.get('/f.txt')?.endsWith('Z')).toBe(true)
  })

  it('fills zeros past the end and creates the file', async () => {
    const accessor = new RAMAccessor(new RAMStore())
    await pwrite(accessor, PATH, ENC.encode('z'), 3)
    expect([...(accessor.store.files.get('/f.txt') ?? [])]).toEqual([0, 0, 0, 122])
  })

  it('refuses a missing parent', async () => {
    const accessor = new RAMAccessor(new RAMStore())
    const nested = new PathSpec({ virtual: '/no/f.txt', directory: '/no/', vfsPath: 'no/f.txt' })
    await expect(pwrite(accessor, nested, ENC.encode('x'), 0)).rejects.toMatchObject({
      code: 'ENOENT',
    })
  })
})
