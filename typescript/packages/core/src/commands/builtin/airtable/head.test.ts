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
import { FakeAirtable, TOKEN } from '../../../core/airtable/_test_util.ts'
import { AirtableVFS } from '../../../vfs/airtable/airtable.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'

const RECORDS =
  '/at/bases/Product_Roadmap__appRoadmapBase001/Features__tblFeatures000001/records.jsonl'
const DEC = new TextDecoder()

async function workspace(fake: FakeAirtable): Promise<Workspace> {
  const mount = new AirtableVFS(
    { token: TOKEN, requestsPerSecond: 10_000, maxReadRecords: 5 },
    { fetchFn: fake.fetch },
  )
  return new Workspace({ '/at/': mount }, { shellParser: await getTestParser() })
}

describe('airtable head', () => {
  it('pushes its line count into maxRecords', async () => {
    const fake = new FakeAirtable()
    const ws = await workspace(fake)
    try {
      const result = await ws.shell(`head -n 2 ${RECORDS}`)
      expect(result.exitCode).toBe(0)
      expect(
        DEC.decode(result.stdout)
          .split('\n')
          .filter((l) => l !== ''),
      ).toHaveLength(2)
    } finally {
      await ws.close()
    }
    expect(fake.recordCalls().map((c) => c.maxRecords)).toEqual(['2'])
  })

  it('refuses the default ten when the table outgrows the cap', async () => {
    const ws = await workspace(new FakeAirtable())
    try {
      const result = await ws.shell(`head ${RECORDS}`)
      // 10 lines asked of a 7-record table under a cap of 5: the full answer
      // would exceed the cap, so it is refused rather than truncated
      expect(result.exitCode).toBe(1)
      expect(DEC.decode(result.stderr)).toBe(`head: error reading '${RECORDS}': File too large\n`)
    } finally {
      await ws.close()
    }
  })

  it('reads the whole file for a byte count', async () => {
    const ws = await workspace(new FakeAirtable())
    try {
      expect((await ws.shell(`head -c 12 ${RECORDS}`)).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })
})
