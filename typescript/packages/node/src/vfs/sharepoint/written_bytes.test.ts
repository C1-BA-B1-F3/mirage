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

import { MountMode } from '@struktoai/mirage-core/types'
import { afterEach, describe, expect, it } from 'vitest'
import {
  DRIVE_ID,
  DRIVE_NAME,
  FakeGraph,
  SITE_NAME,
  serveGraph,
} from '../../core/msgraph/_test_util.ts'
import { Workspace } from '../../workspace.ts'
import { buildVfs } from '../registry.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

let graphs: FakeGraph[] = []

afterEach(async () => {
  await Promise.all(graphs.map((graph) => graph.close()))
  graphs = []
})

async function wsOf(graph: FakeGraph): Promise<Workspace> {
  const vfs = await buildVfs('sharepoint', {
    access_token: 't',
    graph_base_url: graph.url,
    site: SITE_NAME,
    drive: DRIVE_NAME,
  })
  return new Workspace({ '/m': [vfs, MountMode.WRITE] })
}

async function out(workspace: Workspace, command: string): Promise<Uint8Array> {
  const result = await workspace.shell(command)
  expect([result.exitCode, DEC.decode(result.stderr)], command).toEqual([0, ''])
  return result.stdout
}

function promote(path: string, data: Uint8Array): Uint8Array {
  if (!path.endsWith('.docx')) return data
  return new Uint8Array([...data, ...ENC.encode('<promoted/>')])
}

describe('sharepoint written bytes', () => {
  it('keeps no written bytes', async () => {
    const graph = new FakeGraph()
    graphs.push(graph)
    await serveGraph(graph)
    expect((await wsOf(graph)).mount('/m/').vfs.keepsWrittenBytes).toBe(false)
  })

  // Property promotion rewrites Office files on upload, so the bytes tee
  // wrote are not what the library holds; the next cat downloads them.
  it.each(['a.docx', 'a.txt'])('serves what the library stored after tee (%s)', async (name) => {
    const graph = new FakeGraph({ [DRIVE_ID]: { [name]: ENC.encode('old\n') } })
    graphs.push(graph)
    await serveGraph(graph)
    graph.onUpload(promote)
    const ws = await wsOf(graph)
    try {
      await out(ws, `echo hi | tee /m/${name}`)
      const before = graph.fetches()
      expect(DEC.decode(await out(ws, `cat /m/${name}`))).toBe(
        DEC.decode(graph.data(DRIVE_ID, name)),
      )
      expect(graph.fetches() - before).toBe(1)
    } finally {
      await ws.close()
    }
  })
})
