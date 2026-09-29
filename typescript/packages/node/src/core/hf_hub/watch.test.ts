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

import { PathSpec } from '@struktoai/mirage-core/types'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HfHubAccessor } from '../../accessor/hf_hub.ts'
import * as client from './client.ts'
import { parseEntry } from './tree.ts'
import { buildDeltaHook } from './watch.ts'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('hf_hub watch', () => {
  it('raises for a repo it cannot see', async () => {
    // An expired token used to list as an empty repository, which a watch
    // pull reported as every file deleted.
    const accessor = new HfHubAccessor({ repoId: 'acme/widget' } as never)
    accessor.tree = new Map([
      ['a.txt', parseEntry({ type: 'file', oid: 'oid-a', size: 1, path: 'a.txt' })],
    ])
    accessor.treeLoaded = true
    const tree = accessor.tree
    vi.spyOn(client, 'hubGetResponse').mockRejectedValue(new client.HfHubError('expired', 401))
    const root = new PathSpec({ virtual: '/', directory: '/', vfsPath: '' })
    await expect(buildDeltaHook(accessor).pull(root, null)).rejects.toBeInstanceOf(
      client.HfHubError,
    )
    expect(accessor.tree).toBe(tree)
  })
})
