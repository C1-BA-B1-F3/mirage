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
import {
  buildQuery,
  channelDirname,
  dmDirname,
  fileBlobName,
  formatFileGrepResults,
  formatGrepResults,
  userFilename,
} from './formatters.ts'
import type { SearchTarget } from './scope.ts'
import { NAME_MAX_BYTES, byteLength } from '../../utils/sanitize.ts'

const ENC = new TextEncoder()

describe('buildQuery', () => {
  it('returns pattern unchanged when no container', () => {
    const scope: SearchTarget = {}
    expect(buildQuery('hi', scope)).toBe('hi')
  })

  it('prefixes channels with in:#name', () => {
    const scope: SearchTarget = {
      container: 'channels',
      channelName: 'general',
    }
    expect(buildQuery('hi', scope)).toBe('in:#general hi')
  })

  it('prefixes dms with in:@name', () => {
    const scope: SearchTarget = {
      container: 'dms',
      channelName: 'alice',
    }
    expect(buildQuery('hi', scope)).toBe('in:@alice hi')
  })
})

describe('formatGrepResults', () => {
  it('formats matches with channel/date prefix', () => {
    const raw = ENC.encode(
      JSON.stringify({
        messages: {
          matches: [
            {
              channel: { name: 'general', id: 'C1' },
              ts: '1700000000.000100',
              user: 'U1',
              text: 'hello world',
            },
          ],
        },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: 'general',
      channelId: 'C1',
    }
    const lines = formatGrepResults(raw, scope, '/mnt/slack')
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatch(
      /^\/mnt\/slack\/channels\/general__C1\/\d{4}-\d{2}-\d{2}\/chat\.jsonl:\[U1\] hello world$/,
    )
  })

  it('falls back to scope channel info when not present in match', () => {
    const raw = ENC.encode(
      JSON.stringify({
        messages: { matches: [{ ts: '1700000000.0', text: 'hi', username: 'alice' }] },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: 'general',
      channelId: 'C1',
    }
    const lines = formatGrepResults(raw, scope, '/mnt/slack')
    expect(lines[0]).toContain('/channels/general__C1/')
    expect(lines[0]).toContain('[alice] hi')
  })

  it('returns empty when no matches', () => {
    const raw = ENC.encode(JSON.stringify({ messages: { matches: [] } }))
    const scope: SearchTarget = {}
    expect(formatGrepResults(raw, scope, '/mnt/slack')).toEqual([])
  })

  it('replaces newlines in text with spaces', () => {
    const raw = ENC.encode(
      JSON.stringify({
        messages: {
          matches: [{ ts: '1.0', user: 'U1', text: 'a\nb\nc' }],
        },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: 'general',
      channelId: 'C1',
    }
    const lines = formatGrepResults(raw, scope, '/mnt/slack')
    expect(lines[0]).toContain('[U1] a b c')
  })
})

describe('fileBlobName', () => {
  it.each([
    [{ id: 'F1', name: 'report.pdf', title: 'Q4' }, 'report__F1.pdf'],
    [{ id: 'F2', name: '', title: 'design doc.docx' }, 'design doc__F2.docx'],
    [{ id: 'F3' }, 'file__F3'],
  ])('names %j as %s', (meta, expected) => {
    expect(fileBlobName(meta)).toBe(expected)
  })
})

describe('formatFileGrepResults', () => {
  it('emits one line per file match with full path', () => {
    const raw = ENC.encode(
      JSON.stringify({
        files: {
          matches: [
            { id: 'F1', name: 'design.pdf', timestamp: 1700000000 },
            { id: 'F2', title: 'spec.md', timestamp: '1700000500' },
          ],
        },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: 'general',
      channelId: 'C1',
    }
    const lines = formatFileGrepResults(raw, scope, '/mnt/slack')
    expect(lines).toHaveLength(2)
    expect(lines[0]).toMatch(
      /^\/mnt\/slack\/channels\/general__C1\/\d{4}-\d{2}-\d{2}\/files\/design__F1\.pdf:\[file\] design\.pdf$/,
    )
    expect(lines[1]).toContain('files/spec__F2.md:[file] spec.md')
  })

  it('skips matches when scope has no channelId', () => {
    const raw = ENC.encode(
      JSON.stringify({
        files: { matches: [{ id: 'F1', name: 'x.txt', timestamp: 1 }] },
      }),
    )
    const scope: SearchTarget = {}
    expect(formatFileGrepResults(raw, scope, '/mnt/slack')).toEqual([])
  })
})

describe('dirname helpers', () => {
  it('channelDirname', () => {
    expect(channelDirname({ id: 'C1', name: 'general' })).toBe('general__C1')
  })

  it('channelDirname falls back to unknown when name missing', () => {
    expect(channelDirname({ id: 'C456' })).toBe('unknown__C456')
  })

  it('channelDirname preserves spaces and punctuation', () => {
    expect(channelDirname({ id: 'C789', name: 'eng team!' })).toBe('eng team!__C789')
  })

  it('dmDirname uses user_map', () => {
    expect(dmDirname({ id: 'D1', user: 'U1' }, { U1: 'alice' })).toBe('alice__D1')
  })

  it('dmDirname falls back to user id when not in map', () => {
    expect(dmDirname({ id: 'D2', user: 'U2' }, {})).toBe('U2__D2')
  })

  it('dmDirname handles empty user', () => {
    expect(dmDirname({ id: 'D3' }, {})).toBe('unknown__D3')
  })

  it('userFilename ends in .json', () => {
    expect(userFilename({ id: 'U1', name: 'alice' })).toBe('alice__U1.json')
  })

  it('userFilename falls back to unknown when name missing', () => {
    expect(userFilename({ id: 'U2' })).toBe('unknown__U2.json')
  })
})

describe('a long channel name renders one way everywhere', () => {
  const NAME = '会議'.repeat(100)

  it('reports the dirname readdir emits, not a second spelling of it', () => {
    const raw = ENC.encode(
      JSON.stringify({
        messages: {
          matches: [{ channel: { id: 'C001', name: NAME }, ts: '1712707200.0', text: 'hello' }],
        },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: NAME,
      channelId: 'C001',
    }
    const dirname = formatGrepResults(raw, scope, '/slack')[0]
      ?.split('/slack/channels/')[1]
      ?.split('/')[0]

    expect(dirname).toBe(channelDirname({ id: 'C001', name: NAME }))
    expect(byteLength(dirname ?? '')).toBeLessThanOrEqual(NAME_MAX_BYTES)
  })

  it('reports it for file hits too', () => {
    const raw = ENC.encode(
      JSON.stringify({
        files: { matches: [{ id: 'F001', name: 'report.pdf', timestamp: 1712707200 }] },
      }),
    )
    const scope: SearchTarget = {
      container: 'channels',
      channelName: NAME,
      channelId: 'C001',
    }
    const dirname = formatFileGrepResults(raw, scope, '/slack')[0]
      ?.split('/slack/channels/')[1]
      ?.split('/')[0]

    expect(dirname).toBe(channelDirname({ id: 'C001', name: NAME }))
    expect(byteLength(dirname ?? '')).toBeLessThanOrEqual(NAME_MAX_BYTES)
  })
})
