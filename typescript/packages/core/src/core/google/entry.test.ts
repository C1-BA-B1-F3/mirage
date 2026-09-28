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
import type * as DriveModule from './drive.ts'
vi.mock('./drive.ts', async () => {
  const actual = await vi.importActual<typeof DriveModule>('./drive.ts')
  return {
    ...actual,
    getFile: vi.fn(),
    listAllFiles: vi.fn(() => {
      throw new Error('must not search')
    }),
  }
})
import { IndexEntry } from '../../cache/index/config.ts'
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { PathSpec } from '../../types.ts'
import { makeFilename } from '../../vfs/gdocs/doc_entry.ts'
import { detectScope } from '../gdocs/scope.ts'
import { GoogleApiError, type TokenManager } from './client.ts'
import { getFile } from './drive.ts'
import { resolveAppEntry } from './entry.ts'

const ITEM = {
  id: 'doc1',
  name: 'Notes',
  mimeType: 'application/vnd.google-apps.document',
  modifiedTime: '2026-04-01T12:00:00Z',
  owners: [{ me: true }],
  size: '1000',
}
const NAME = makeFilename(ITEM.name, ITEM.id, ITEM.modifiedTime)
const PATH = new PathSpec({
  virtual: `/docs/owned/${NAME}`,
  directory: `/docs/owned/${NAME}`,
  vfsPath: `owned/${NAME}`,
})
const TM = {} as TokenManager

describe('direct lookup after incomplete search', () => {
  it.each([
    'updated',
    'renamed',
    'date',
    'trashed',
    'mime',
    'owner',
    'deleted',
    'forbidden',
    'unavailable',
  ])('%s', async (outcome) => {
    vi.mocked(getFile).mockReset()
    const index = new RAMIndexCacheStore()
    await index.put(
      PATH.virtual,
      new IndexEntry({
        id: 'doc1',
        name: 'Notes',
        vfsName: NAME,
        resourceType: 'gdocs/file',
        remoteTime: 'old',
      }),
    )
    await index.invalidate()
    const item: DriveModule.DriveFile = { ...ITEM }
    if (outcome === 'renamed') item.name = 'Renamed'
    if (outcome === 'date') item.modifiedTime = '2026-04-02T12:00:00Z'
    if (outcome === 'trashed') item.trashed = true
    if (outcome === 'mime') item.mimeType = 'text/plain'
    if (outcome === 'owner') item.owners = []
    const statuses: Record<string, number> = { deleted: 404, forbidden: 403, unavailable: 503 }
    const status = statuses[outcome]
    const error = status === undefined ? null : new GoogleApiError('failed', status)
    if (error) vi.mocked(getFile).mockRejectedValue(error)
    else vi.mocked(getFile).mockResolvedValue(item)
    const result = resolveAppEntry(
      TM,
      detectScope(PATH),
      PATH,
      index,
      ITEM.mimeType,
      'gdocs/file',
      makeFilename,
    )
    if (outcome === 'updated') {
      const entry = await result
      expect(entry.remoteTime).toBe(ITEM.modifiedTime)
      expect(entry.size).toBeNull()
      expect(entry.extra).toEqual({ source_size: 1000 })
    } else if (outcome === 'forbidden' || outcome === 'unavailable') {
      await expect(result).rejects.toBe(error)
      expect((await index.get(PATH.virtual)).entry).toBeDefined()
    } else {
      await expect(result).rejects.toMatchObject({ code: 'ENOENT' })
      expect((await index.get(PATH.virtual)).entry).toBeUndefined()
    }
    expect(getFile).toHaveBeenCalledExactlyOnceWith(TM, 'doc1')
    await index.close()
  })
})

describe('only a complete live listing proves absence', () => {
  it.each(['complete', 'partial', 'expired'])('%s', async (listing) => {
    vi.mocked(getFile).mockReset().mockResolvedValue(ITEM)
    const index = new RAMIndexCacheStore()
    try {
      if (listing === 'partial') await index.setPartialDir('/docs/owned', [])
      else await index.setDir('/docs/owned', [])
      if (listing === 'expired') await index.invalidate()
      const result = resolveAppEntry(
        TM,
        detectScope(PATH),
        PATH,
        index,
        ITEM.mimeType,
        'gdocs/file',
        makeFilename,
      )
      if (listing === 'complete') {
        await expect(result).rejects.toMatchObject({ code: 'ENOENT' })
        expect(getFile).not.toHaveBeenCalled()
      } else {
        expect((await result).id).toBe(ITEM.id)
        expect(getFile).toHaveBeenCalledExactlyOnceWith(TM, 'doc1')
      }
    } finally {
      await index.close()
    }
  })
})
