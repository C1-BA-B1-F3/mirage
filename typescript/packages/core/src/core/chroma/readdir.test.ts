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

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type * as ClientModule from './client.ts'

vi.mock('./client.ts', async () => {
  const actual = await vi.importActual<typeof ClientModule>('./client.ts')
  return { ...actual, fetchPathTree: vi.fn() }
})

import type { ChromaAccessor } from '../../accessor/chroma.ts'
import { RAMFileCacheStore } from '../../cache/file/ram.ts'
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { IndexView } from '../../cache/index/view.ts'
import { PathSpec } from '../../types.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import * as clientMod from './client.ts'
import { readdir } from './readdir.ts'

const ACCESSOR = {} as ChromaAccessor

function pathAt(virtual: string): PathSpec {
  return new PathSpec({ vfsPath: mountKey(virtual, '/knowledge'), virtual, directory: virtual })
}

function refusing(index: RAMIndexCacheStore): IndexView {
  return new IndexView(index, new RAMFileCacheStore(), '/knowledge', () => true, {
    mayServeListing: () => Promise.resolve(false),
  })
}

describe('chroma readdir on an expired listing', () => {
  beforeEach(() => {
    vi.mocked(clientMod.fetchPathTree).mockReset()
    vi.mocked(clientMod.fetchPathTree).mockResolvedValue(
      JSON.stringify({ 'guides/quickstart': {}, 'api/reference': {} }),
    )
  })

  // The tree is written whole, so an expired folder listing means the tree
  // aged out, not that the folder is gone: refill and answer.
  it('refills an expired folder under a live root', async () => {
    const index = new RAMIndexCacheStore()
    await readdir(ACCESSOR, pathAt('/knowledge/guides'), index)
    await index.setDir('/knowledge/guides', [], new Date(Date.now() - 1000))
    expect(await readdir(ACCESSOR, pathAt('/knowledge/guides'), index)).toEqual([
      '/knowledge/guides/quickstart',
    ])
  })

  // A read outside any command under fresh has every cached listing
  // refused; answering ENOENT would fail every such ls of a subfolder.
  it('refills and answers a refused folder listing', async () => {
    const view = refusing(new RAMIndexCacheStore())
    await readdir(ACCESSOR, pathAt('/knowledge/guides'), view)
    expect(await readdir(ACCESSOR, pathAt('/knowledge/guides'), view)).toEqual([
      '/knowledge/guides/quickstart',
    ])
  })

  it('keeps a folder the tree lacks ENOENT', async () => {
    await expect(
      readdir(ACCESSOR, pathAt('/knowledge/nope'), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('refills and answers a refused root listing', async () => {
    const view = refusing(new RAMIndexCacheStore())
    await readdir(ACCESSOR, pathAt('/knowledge'), view)
    expect((await readdir(ACCESSOR, pathAt('/knowledge'), view)).sort()).toEqual([
      '/knowledge/api',
      '/knowledge/guides',
    ])
  })
  it.each(['/knowledge', '/knowledge/guides'])(
    'fetches a refused listing once: %s',
    async (path) => {
      const view = refusing(new RAMIndexCacheStore())
      for (let i = 0; i < 2; i++) {
        vi.mocked(clientMod.fetchPathTree).mockClear()
        expect(await readdir(ACCESSOR, pathAt(path), view)).not.toHaveLength(0)
        expect(clientMod.fetchPathTree).toHaveBeenCalledTimes(1)
      }
    },
  )
})
