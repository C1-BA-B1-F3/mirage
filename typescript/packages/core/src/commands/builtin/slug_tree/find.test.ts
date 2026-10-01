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
import type * as ClientModule from '../../../core/dify/client.ts'

vi.mock('../../../core/dify/client.ts', async () => {
  const actual = await vi.importActual<typeof ClientModule>('../../../core/dify/client.ts')
  return {
    ...actual,
    listAllDocuments: vi.fn(() =>
      Promise.resolve([
        doc('doc-1', 'Guide', 'guides/quickstart.md'),
        doc('doc-2', 'Guide 2', 'guides/deep/note.md'),
      ]),
    ),
    getDocumentDetail: vi.fn(() => Promise.reject(new Error('unexpected document-detail call'))),
  }
})

import type { DifyAccessor } from '../../../accessor/dify.ts'
import { RAMIndexCacheStore } from '../../../cache/index/ram.ts'
import { runWithSession } from '../../../context/session_context.ts'
import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { mountKey } from '../../../utils/key_prefix.ts'
import { SessionState } from '../../../workspace/session/session.ts'
import { DIFY_COMMANDS } from '../dify/index.ts'
import { readsTimes } from './find.ts'

function doc(id: string, name: string, slug: string): Record<string, unknown> {
  return {
    id,
    name,
    doc_metadata: [{ name: 'slug', value: slug }],
    enabled: true,
    indexing_status: 'completed',
    archived: false,
    tokens: 4,
    data_source_type: 'upload_file',
    data_source_detail_dict: { upload_file: { size: 12 } },
    created_at: 1716282000,
  }
}

describe('readsTimes', () => {
  it.each([
    [['-name', '*.md'], false],
    [['-mtime', '-1'], true],
    [['-newer', '/knowledge/README.md'], true],
    [['-newermt', '2024-01-01'], true],
    [['-printf', '%p %s\n'], false],
    [['-printf', '%TY %p\n'], true],
  ])('only an expression that reads times pays the full stat: %j', (texts, reads) => {
    expect(readsTimes(texts)).toBe(reads)
  })
})

describe('slug-tree find under a hide', () => {
  it('a hidden child leaves its directory empty', async () => {
    const find = DIFY_COMMANDS.find((c) => c.name === 'find')
    if (find === undefined) throw new Error('dify registers no find')
    const accessor = { config: { slugMetadataName: 'slug' } } as DifyAccessor
    const guides = new PathSpec({
      virtual: '/knowledge/guides',
      directory: '/knowledge/guides',
      vfsPath: mountKey('/knowledge/guides', '/knowledge'),
    })
    const sess = new SessionState({ sessionId: 'veiled' })
    sess.hiddenPaths = { paths: ['/knowledge/guides/deep/note.md'] }
    const opts = {
      stdin: null,
      flags: {},
      filetypeFns: null,
      cwd: '/',
      index: new RAMIndexCacheStore(),
    }
    const result = await runWithSession(sess, async () =>
      find.fn(accessor, [guides], ['-empty'], opts),
    )
    const [stdout, io] = result ?? [null, null]
    expect(new TextDecoder().decode(await materialize(stdout))).toBe('/knowledge/guides/deep\n')
    expect(io?.exitCode).toBe(0)
  })
})
