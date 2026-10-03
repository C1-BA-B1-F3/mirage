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
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { API, makeAccessor, spec } from './_test_util.ts'

vi.mock('./client.ts', async () => (await import('./_test_util.ts')).CLIENT)

const { unlink } = await import('./unlink.ts')

let index: RAMIndexCacheStore

beforeEach(() => {
  API.reset()
  index = new RAMIndexCacheStore()
})

describe('gcal unlink', () => {
  // The entry resolves through the parent bucket's one listing first, so an
  // unlisted name is refused without a destructive call.
  it.each([
    [1, '/primary/2026-08-11/aaaa1__0900-1030_PhD_Defense.gcal.json'],
    [7, '/primary/2026-08-10--2026-08-16/aaaa1__2026-08-11_0900-1030_PhD_Defense.gcal.json'],
  ])('deletes the event a %i-day name carries', async (size, path) => {
    await unlink(makeAccessor({ bucket_days: size }), spec(path), index)
    expect(API.deleted).toEqual([['integ@example.com', 'aaaa1']])
    expect(API.listed.map((call) => call[0])).toEqual(['integ@example.com'])
  })

  // accessRole reader and freeBusyReader: refused at the mount rather than
  // surfacing a 403 after the call has already gone out.
  it.each([
    ['/primary/2026-08-11', 'EISDIR'],
    [
      '/Engineering__team@group.calendar.google.com/2026-08-11/aaaa1__0900-1030_PhD_Defense.gcal.json',
      'EACCES',
    ],
    ['/Exec__busy@group.calendar.google.com/2026-08-11/aaaa1__0900-1030_busy.gcal.json', 'EACCES'],
    ['/nope/2026-08-11/aaaa1__0900-1030_X.gcal.json', 'ENOENT'],
  ])('refuses %s with %s and deletes nothing', async (path, code) => {
    await expect(unlink(makeAccessor(), spec(path), index)).rejects.toMatchObject({ code })
    expect(API.deleted).toEqual([])
  })
})
