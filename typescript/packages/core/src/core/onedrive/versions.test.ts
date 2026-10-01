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

import { afterEach, describe, expect, it, vi } from 'vitest'

import { OneDriveAccessor } from '../../accessor/onedrive.ts'
import { PathSpec } from '../../types.ts'
import { listVersions } from './versions.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OneDrive version history', () => {
  it('lists the versions of the item under the keyPrefix', async () => {
    const versions = [{ id: '2.0' }, { id: '1.0' }]
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ value: versions })))
    vi.stubGlobal('fetch', fetchMock)
    const accessor = new OneDriveAccessor({ accessToken: 'token', keyPrefix: 'team' })
    expect(await listVersions(accessor, PathSpec.fromStrPath('/od/a.txt', 'a.txt'))).toEqual(
      versions,
    )
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      'https://graph.microsoft.com/v1.0/me/drive/root:/team/a.txt:/versions',
    )
  })
})
