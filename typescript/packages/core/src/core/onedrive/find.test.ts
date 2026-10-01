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
import { find } from './find.ts'

const BASE = 'https://graph.microsoft.com/v1.0/me/drive'

function graph(routes: Record<string, unknown>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown) => {
      const url = String(input).split('?')[0] ?? ''
      const body = routes[url]
      return Promise.resolve(
        body === undefined
          ? new Response(JSON.stringify({ error: { code: 'itemNotFound' } }), { status: 404 })
          : new Response(JSON.stringify(body), { status: 200 }),
      )
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OneDrive find', () => {
  it('matches -empty against a childless folder', async () => {
    graph({
      [`${BASE}/root/children`]: {
        value: [
          { id: '1', name: 'a.txt', size: 3, file: {} },
          { id: '2', name: 'hollow', folder: { childCount: 0 } },
          { id: '3', name: 'full', folder: { childCount: 1 } },
        ],
      },
      [`${BASE}/root:/hollow:/children`]: { value: [] },
      [`${BASE}/root:/full:/children`]: { value: [{ id: '4', name: 'c.txt', size: 1, file: {} }] },
    })
    const accessor = new OneDriveAccessor({ accessToken: 'token' })
    expect(
      await find(accessor, PathSpec.fromStrPath('/od', ''), { type: 'd', empty: true }),
    ).toEqual(['/hollow'])
  })

  // The start-row probe answers whether the start is a directory, so a
  // start gone by the time it asks is "no", not an error.
  it.each([
    [{ id: 'gone', name: 'gone', folder: { childCount: 0 } }, ['/gone']],
    [undefined, []],
  ])('emits an empty start only while it still exists (%o)', async (item, rows) => {
    graph({ [`${BASE}/root:/gone:/children`]: { value: [] }, [`${BASE}/root:/gone`]: item })
    const accessor = new OneDriveAccessor({ accessToken: 'token' })
    expect(await find(accessor, PathSpec.fromStrPath('/od/gone', 'gone'))).toEqual(rows)
  })
})
