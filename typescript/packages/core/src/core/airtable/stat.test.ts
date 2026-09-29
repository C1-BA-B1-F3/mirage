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
import { ContentType, FileType, PathSpec } from '../../types.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import { FakeAirtable, makeAccessor } from './_test_util.ts'
import { read } from './read.ts'
import { stat } from './stat.ts'

const ROOT = '/at'
const BASE = `${ROOT}/bases/Product_Roadmap__appRoadmapBase001`
const TABLE = `${BASE}/Features__tblFeatures000001`

function spec(virtual: string): PathSpec {
  return new PathSpec({
    virtual,
    directory: virtual.slice(0, virtual.lastIndexOf('/')),
    vfsPath: mountKey(virtual, ROOT),
  })
}

describe('airtable stat', () => {
  it('sizes json leaves at their rendered byte length', async () => {
    const accessor = makeAccessor(new FakeAirtable())
    const index = new RAMIndexCacheStore()
    for (const leaf of [`${BASE}/base.json`, `${TABLE}/table.json`]) {
      const info = await stat(accessor, spec(leaf), index)
      const body = await read(accessor, spec(leaf), index)
      expect(info.type).toBe(FileType.FILE)
      expect(info.content).toBe(ContentType.JSON)
      expect(info.size).toBe(body.byteLength)
    }
  })

  it('leaves record files size-unknown', async () => {
    const accessor = makeAccessor(new FakeAirtable())
    const index = new RAMIndexCacheStore()
    const records = await stat(accessor, spec(`${TABLE}/records.jsonl`), index)
    const view = await stat(
      accessor,
      spec(`${TABLE}/views/Done_shipped__viwDone0000000001.jsonl`),
      index,
    )
    expect(records.size).toBeNull()
    expect(view.size).toBeNull()
    expect(view.extra).toEqual({ view_id: 'viwDone0000000001' })
  })

  it('stats directories as directories', async () => {
    const accessor = makeAccessor(new FakeAirtable())
    const index = new RAMIndexCacheStore()
    for (const path of [`${ROOT}/bases`, BASE, TABLE, `${TABLE}/views`]) {
      expect((await stat(accessor, spec(path), index)).type).toBe(FileType.DIRECTORY)
    }
  })

  it('answers ENOENT for an unlisted view', async () => {
    await expect(
      stat(
        makeAccessor(new FakeAirtable()),
        spec(`${TABLE}/views/Gone__viwGone0000000001.jsonl`),
        new RAMIndexCacheStore(),
      ),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })
})
