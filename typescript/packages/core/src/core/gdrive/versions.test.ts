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
import type * as ClientModule from '../google/client.ts'

vi.mock('../google/client.ts', async () => {
  const actual = await vi.importActual<typeof ClientModule>('../google/client.ts')
  return { ...actual, googleGet: vi.fn(), googleGetBytes: vi.fn() }
})

import type { TokenManager } from '../google/client.ts'
import { googleGet, googleGetBytes } from '../google/client.ts'
import { captureFileMetadata, downloadRevision } from './versions.ts'

const TM = { config: { clientId: 'cid', refreshToken: 'rt' } } as TokenManager

describe('gdrive versions', () => {
  it('downloadRevision hits the revision URL', async () => {
    const enc = new TextEncoder()
    vi.mocked(googleGetBytes).mockResolvedValue(enc.encode('old'))
    const data = await downloadRevision(TM, 'f1', 'r1')
    expect(new TextDecoder().decode(data)).toBe('old')
    const call = vi.mocked(googleGetBytes).mock.calls.at(-1)
    expect(call?.[1]).toContain('/files/f1/revisions/r1?alt=media')
  })

  it('captureFileMetadata returns the md5 and head revision raw', async () => {
    // Raw, not coalesced: the caller checks the md5 against the bytes.
    vi.mocked(googleGet).mockResolvedValueOnce({ headRevisionId: 'r9', md5Checksum: 'abc' })
    expect(await captureFileMetadata(TM, 'f1')).toEqual(['abc', 'r9'])
    vi.mocked(googleGet).mockResolvedValueOnce({ headRevisionId: 'r9' })
    expect(await captureFileMetadata(TM, 'f1')).toEqual([null, 'r9'])
  })
})
