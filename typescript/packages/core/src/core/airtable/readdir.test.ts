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
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { PathSpec } from '../../types.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import { FakeAirtable, makeAccessor } from './_test_util.ts'
import { readdir } from './readdir.ts'

const ROOT = '/at'
const BASE = `${ROOT}/bases/Product_Roadmap__appRoadmapBase001`
const TABLE = `${BASE}/Features__tblFeatures000001`

function spec(virtual: string): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath: mountKey(virtual, ROOT) })
}

describe('airtable readdir', () => {
  it('roots at the bases directory', async () => {
    const out = await readdir(
      makeAccessor(new FakeAirtable()),
      spec(`${ROOT}/`),
      new RAMIndexCacheStore(),
    )
    expect(out).toEqual([`${ROOT}/bases`])
  })

  it('lists bases as named directories', async () => {
    const out = await readdir(
      makeAccessor(new FakeAirtable()),
      spec(`${ROOT}/bases`),
      new RAMIndexCacheStore(),
    )
    expect(out).toEqual([
      `${ROOT}/bases/Product_Roadmap__appRoadmapBase001`,
      `${ROOT}/bases/Ops_Finance__appOpsFinance0001`,
    ])
  })

  it('lists base.json and the tables of a base', async () => {
    const out = await readdir(
      makeAccessor(new FakeAirtable()),
      spec(BASE),
      new RAMIndexCacheStore(),
    )
    expect(out).toEqual([`${BASE}/base.json`, TABLE])
  })

  it('seeds every table and views dir from one schema call', async () => {
    const fake = new FakeAirtable()
    const accessor = makeAccessor(fake)
    const index = new RAMIndexCacheStore()
    await readdir(accessor, spec(BASE), index)
    const before = fake.calls.length
    const table = await readdir(accessor, spec(TABLE), index)
    const views = await readdir(accessor, spec(`${TABLE}/views`), index)
    expect(fake.calls).toHaveLength(before)
    expect(table).toEqual([`${TABLE}/table.json`, `${TABLE}/records.jsonl`, `${TABLE}/views`])
    expect(views).toEqual([
      `${TABLE}/views/Grid_view__viwGrid0000000001.jsonl`,
      `${TABLE}/views/Done_shipped__viwDone0000000001.jsonl`,
    ])
  })

  it('warms a cold table listing through its base', async () => {
    const out = await readdir(
      makeAccessor(new FakeAirtable()),
      spec(TABLE),
      new RAMIndexCacheStore(),
    )
    expect(out).toContain(`${TABLE}/records.jsonl`)
  })

  it('answers ENOENT for an unknown or out-of-scope base', async () => {
    const fake = new FakeAirtable()
    await expect(
      readdir(
        makeAccessor(fake),
        spec(`${ROOT}/bases/X__appNope000000001`),
        new RAMIndexCacheStore(),
      ),
    ).rejects.toMatchObject({ code: 'ENOENT' })
    await expect(
      readdir(
        makeAccessor(fake, { baseIds: ['appOpsFinance0001'] }),
        spec(BASE),
        new RAMIndexCacheStore(),
      ),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })
})
