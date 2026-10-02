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
import { ContentType, FileType } from '../../types.ts'
import { compactJsonBytes } from '../render/json.ts'
import { API, EVENTS, makeAccessor, spec } from './_test_util.ts'

vi.mock('./client.ts', async () => (await import('./_test_util.ts')).CLIENT)

const { stat } = await import('./stat.ts')

const WEEK = '/primary/2026-08-10--2026-08-16'

let index: RAMIndexCacheStore

beforeEach(() => {
  API.reset()
  index = new RAMIndexCacheStore()
})

describe('gcal stat', () => {
  it('reports the root as a directory', async () => {
    expect((await stat(makeAccessor(), spec('/'), index)).type).toBe(FileType.DIRECTORY)
  })

  // The range query is positive proof of what is there, so a bucket with no
  // events is an empty directory rather than ENOENT.
  it.each([
    [1, '/primary'],
    [1, '/primary/2026-08-11'],
    [7, WEEK],
    [1, '/primary/2027-03-04'],
    [7, '/primary/2027-03-01--2027-03-07'],
  ])('reports %i-day %s as a directory', async (size, path) => {
    const row = await stat(makeAccessor({ bucket_days: size }), spec(path), index)
    expect(row.type).toBe(FileType.DIRECTORY)
    expect(row.name).toBe(path.slice(path.lastIndexOf('/') + 1))
  })

  it.each([
    [1, '/primary/2026-08-11/aaaa1__0900-1030_PhD_Defense.gcal.json'],
    [7, `${WEEK}/aaaa1__2026-08-11_0900-1030_PhD_Defense.gcal.json`],
  ])('reports a %i-day event as JSON sized as rendered', async (size, path) => {
    const row = await stat(makeAccessor({ bucket_days: size }), spec(path), index)
    expect(row.content).toBe(ContentType.JSON)
    expect(row.extra.event_id).toBe('aaaa1')
    // The rendered payload's byte length, never a source-side number.
    expect(row.size).toBe(compactJsonBytes(EVENTS[0] ?? {}).length)
  })

  it('reports calendar.json as JSON', async () => {
    const row = await stat(makeAccessor(), spec('/primary/calendar.json'), index)
    expect(row.content).toBe(ContentType.JSON)
  })

  // Shape alone used to be enough, so stat reported a directory that readdir
  // then raised on.
  it.each([
    [1, '/nope/2027-03-04'],
    [1, '/primary/not-a-date'],
    [1, '/primary/2026-02-30'],
    [1, '/primary/2026-13-01'],
    [1, '/primary/2026-08-11/zzzz9__0000-0100_Nope.gcal.json'],
    [7, '/primary/2026-08-11'],
    [7, '/primary/2026-08-11--2026-08-17'],
  ])('is ENOENT on a %i-day mount for %s', async (size, path) => {
    await expect(stat(makeAccessor({ bucket_days: size }), spec(path), index)).rejects.toThrow()
  })
})
