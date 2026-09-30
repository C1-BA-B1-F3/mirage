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
import { HfHubAccessor } from '../../accessor/hf_hub.ts'
import * as client from './client.ts'
import { headCommit, revisionUrl } from './repo.ts'

function accessor(config: Record<string, unknown> = {}): HfHubAccessor {
  return new HfHubAccessor({ repoId: 'acme/widget', ...config } as never)
}

describe('headCommit', () => {
  it('reads the sha', async () => {
    const spy = vi.spyOn(client, 'hubGet').mockResolvedValue({ sha: 'deadbeef' })
    expect(await headCommit(accessor())).toBe('deadbeef')
    spy.mockRestore()
  })

  it('asks the revision, not the bare repo', async () => {
    // The bare repo object answers the default branch's sha whatever
    // revision was asked for, and the download cache is keyed by this sha,
    // so reading it there files a `--revision dev` fetch under main's
    // snapshot and points refs/dev at it.
    const spy = vi.spyOn(client, 'hubGet').mockResolvedValue({ sha: 'deadbeef' })
    await headCommit(accessor({ revision: 'dev' }))
    expect(String(spy.mock.calls[0]?.[1])).toMatch(/\/revision\/dev$/)
    spy.mockRestore()
  })

  it('is empty when the Hub reports none', async () => {
    const spy = vi.spyOn(client, 'hubGet').mockResolvedValue({})
    expect(await headCommit(accessor())).toBe('')
    spy.mockRestore()
  })

  it('is empty when the Hub answered something that is not an object', async () => {
    const spy = vi.spyOn(client, 'hubGet').mockResolvedValue([])
    expect(await headCommit(accessor())).toBe('')
    spy.mockRestore()
  })
})

describe('revisionUrl', () => {
  it('encodes a revision holding a slash', () => {
    expect(revisionUrl(accessor({ revision: 'feature/foo' }))).toMatch(/\/revision\/feature%2Ffoo$/)
  })
})
