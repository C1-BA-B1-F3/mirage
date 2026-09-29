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
import type * as ApiModule from './api.ts'

vi.mock('./api.ts', async () => {
  const actual = await vi.importActual<typeof ApiModule>('./api.ts')
  return { ...actual, listFolderItems: vi.fn() }
})

import { BoxAccessor } from '../../accessor/box.ts'
import * as api from './api.ts'
import type { BoxItem } from './api.ts'
import type { BoxTokenManager } from './client.ts'
import { mountRelativeKey, resolveChain, resolveItem } from './resolve.ts'

const FOLDERS: Record<string, BoxItem[]> = {
  '0': [
    { type: 'folder', id: '10', name: 'team' },
    { type: 'file', id: '2', name: 'a.txt' },
  ],
  '10': [{ type: 'folder', id: '11', name: 'docs' }],
  '11': [],
}

const ACCESSOR = new BoxAccessor({ tokenManager: {} as BoxTokenManager })

beforeEach(() => {
  vi.mocked(api.listFolderItems).mockReset()
  vi.mocked(api.listFolderItems).mockImplementation((_tm, folderId) =>
    Promise.resolve(FOLDERS[folderId] ?? []),
  )
})

describe('box resolve', () => {
  it('stops the chain at the first missing component', async () => {
    const chain = await resolveChain(ACCESSOR, ['team', 'gone', 'x'])
    expect(chain.map((c) => c.id)).toEqual(['10'])
  })

  it('never lists a file', async () => {
    const chain = await resolveChain(ACCESSOR, ['a.txt', 'x'])
    expect(chain.map((c) => c.id)).toEqual(['2'])
    expect(vi.mocked(api.listFolderItems).mock.calls.map((c) => c[1])).toEqual(['0'])
  })

  it('resolves an item only for the whole path', async () => {
    expect((await resolveItem(ACCESSOR, ['team', 'docs']))?.id).toBe('11')
    expect((await resolveItem(ACCESSOR, ['a.txt']))?.id).toBe('2')
    expect(await resolveItem(ACCESSOR, ['team', 'gone'])).toBeNull()
    expect(await resolveItem(ACCESSOR, ['a.txt', 'x'])).toBeNull()
    expect(await resolveItem(ACCESSOR, [])).toBeNull()
  })

  it('trims a path_collection through the mount root', () => {
    const item = {
      name: 'a.txt',
      path_collection: {
        total_count: 3,
        entries: [
          { type: 'folder' as const, id: '0', name: 'All Files' },
          { type: 'folder' as const, id: '10', name: 'team' },
          { type: 'folder' as const, id: '11', name: 'docs' },
        ],
      },
    }
    expect(mountRelativeKey(item, '0')).toBe('team/docs/a.txt')
    expect(mountRelativeKey(item, '10')).toBe('docs/a.txt')
    expect(mountRelativeKey(item, '99')).toBeNull()
  })
})
