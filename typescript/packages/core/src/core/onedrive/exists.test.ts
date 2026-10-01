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
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { PathSpec } from '../../types.ts'
import { exists } from './exists.ts'
import { readdir } from './readdir.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OneDrive exists', () => {
  it('answers from the index a listing filled, without a request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ value: [{ id: '1', name: 'a.txt', size: 1, file: {} }] })),
      )
    vi.stubGlobal('fetch', fetchMock)
    const accessor = new OneDriveAccessor({ accessToken: 'token' })
    const index = new RAMIndexCacheStore()
    await readdir(accessor, PathSpec.fromStrPath('/od', ''), index)
    expect(await exists(accessor, PathSpec.fromStrPath('/od/a.txt', 'a.txt'), index)).toBe(true)
    expect(await exists(accessor, PathSpec.fromStrPath('/od/b.txt', 'b.txt'), index)).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
