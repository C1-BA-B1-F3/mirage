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

import { describe, expect, it, vi } from 'vitest'

import { RAMFileCacheStore } from '../../cache/file/ram.ts'
import { IndexEntry } from '../../cache/index/config.ts'
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { IndexView } from '../../cache/index/view.ts'
import { PathSpec } from '../../types.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import { gnuBasename } from '../../utils/path.ts'
import { dirRows } from './rows.ts'
import { SlugTree, virtualKeyFor } from './tree.ts'

const FILES = new Map([
  ['/guides/quickstart', 5],
  ['/api/reference', 3],
])

function fileEntry(path: string, size: number): IndexEntry {
  return new IndexEntry({ id: path.slice(1), name: gnuBasename(path), resourceType: 'file', size })
}

function fakeTree(): { tree: SlugTree<null>; load: ReturnType<typeof vi.fn> } {
  const load = vi.fn((_accessor: null, prefix: string) =>
    Promise.resolve(dirRows(FILES, prefix, fileEntry)),
  )
  return { tree: new SlugTree<null>(load), load }
}

function pathAt(virtual: string): PathSpec {
  return new PathSpec({ vfsPath: mountKey(virtual, '/knowledge'), virtual, directory: virtual })
}

function refusing(index: RAMIndexCacheStore): IndexView {
  return new IndexView(index, new RAMFileCacheStore(), '/knowledge', () => true, {
    mayServeListing: () => Promise.resolve(false),
  })
}

describe('slug tree readdir on an expired listing', () => {
  // The tree is written whole, so an expired folder listing means the tree
  // aged out, not that the folder is gone: refill and answer.
  it('refilled rows respect index ownership', async () => {
    const { tree } = fakeTree()
    const view = new IndexView(
      new RAMIndexCacheStore(),
      new RAMFileCacheStore(),
      '/knowledge',
      (key) => !key.startsWith('/knowledge/guides'),
    )
    for (let i = 0; i < 2; i++) {
      expect(await tree.readdir(null, pathAt('/knowledge'), view)).toEqual(['/knowledge/api'])
    }
  })

  it('refills an expired folder under a live root', async () => {
    const { tree } = fakeTree()
    const index = new RAMIndexCacheStore()
    await tree.readdir(null, pathAt('/knowledge/guides'), index)
    await index.setDir('/knowledge/guides', [], new Date(Date.now() - 1000))
    expect(await tree.readdir(null, pathAt('/knowledge/guides'), index)).toEqual([
      '/knowledge/guides/quickstart',
    ])
  })

  it('keeps a folder the tree lacks ENOENT', async () => {
    const { tree } = fakeTree()
    await expect(
      tree.readdir(null, pathAt('/knowledge/nope'), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('refuses a file with ENOTDIR naming the path', async () => {
    const { tree } = fakeTree()
    await expect(
      tree.readdir(null, pathAt('/knowledge/guides/quickstart'), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOTDIR', virtualPath: '/knowledge/guides/quickstart' })
  })

  // A read outside any command under fresh has every cached listing
  // refused; answering ENOENT would fail every such ls of a subfolder.
  it.each([
    ['/knowledge', ['/knowledge/api', '/knowledge/guides']],
    ['/knowledge/guides', ['/knowledge/guides/quickstart']],
  ])('refills a refused listing once and answers: %s', async (path, children) => {
    const { tree, load } = fakeTree()
    const view = refusing(new RAMIndexCacheStore())
    for (let i = 0; i < 2; i++) {
      load.mockClear()
      expect(await tree.readdir(null, pathAt(path), view)).toEqual(children)
      expect(load).toHaveBeenCalledTimes(1)
    }
  })
})

describe('virtualKeyFor', () => {
  it('maps the mount root and keeps prefixed paths', () => {
    expect(virtualKeyFor(pathAt('/knowledge'))).toBe('/knowledge')
    expect(virtualKeyFor(pathAt('/knowledge/'))).toBe('/knowledge')
    expect(virtualKeyFor(pathAt('/knowledge/guides/auth.md'))).toBe('/knowledge/guides/auth.md')
  })

  it('normalizes when no prefix is set', () => {
    const ps = (virtual: string) =>
      new PathSpec({ virtual, directory: virtual, vfsPath: mountKey(virtual, '') })
    expect(virtualKeyFor(ps('/guides/'))).toBe('/guides')
    expect(virtualKeyFor(ps('/'))).toBe('/')
  })

  it('uses the directory for glob patterns', () => {
    const spec = new PathSpec({
      virtual: '/knowledge/guides/*.md',
      directory: '/knowledge/guides/',
      pattern: '*.md',
      resolved: false,
      vfsPath: mountKey('/knowledge/guides/*.md', '/knowledge'),
    })
    expect(virtualKeyFor(spec)).toBe('/knowledge/guides')
  })
})
