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
import { MongoDBAccessor } from '../../accessor/mongodb.ts'
import { PathSpec } from '../../types.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import { resolveMongoDBConfig } from '../../vfs/mongodb/config.ts'
import { arrayIter, stubMongoDriver } from './_test_util.ts'
import { readStream, watchStream } from './stream.ts'

function docs(database: string): PathSpec {
  const virtual = `/mongo/${database}/collections/users/documents.jsonl`
  return new PathSpec({
    virtual,
    directory: `/mongo/${database}/collections/users/`,
    resolved: true,
    vfsPath: mountKey(virtual, '/mongo'),
  })
}

async function drain(stream: AsyncIterable<Uint8Array>): Promise<string> {
  let out = ''
  for await (const chunk of stream) out += new TextDecoder().decode(chunk)
  return out
}

describe('mongodb document streams', () => {
  const queried: string[] = []
  const driver = stubMongoDriver({
    listDatabases: () => Promise.resolve(['app', 'secret']),
    listCollections: () => Promise.resolve(['users']),
    iterDocuments: (database) => {
      queried.push(database)
      return arrayIter([{ _id: 1, name: 'ada' }])()
    },
    iterInserts: (database) => {
      queried.push(database)
      return arrayIter([{ _id: 2, name: 'ben' }])()
    },
  })
  const accessor = new MongoDBAccessor(
    driver,
    resolveMongoDBConfig({ uri: 'mongodb://h', databases: ['app'] }),
  )

  // Both streams went straight to the collection the path names, so a
  // database `databases` leaves out streamed while `ls` and `stat` said it was
  // not there.
  it('refuses a collection outside databases before querying it', async () => {
    for (const open of [readStream, watchStream]) {
      await expect(drain(open(accessor, docs('secret')))).rejects.toMatchObject({ code: 'ENOENT' })
    }
    expect(queried).toEqual([])
    expect(await drain(readStream(accessor, docs('app')))).toContain('"ada"')
    expect(queried).toEqual(['app'])
  })
})
