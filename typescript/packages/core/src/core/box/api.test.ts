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

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type * as ClientModule from './client.ts'

vi.mock('./client.ts', async () => {
  const actual = await vi.importActual<typeof ClientModule>('./client.ts')
  return { ...actual, boxGet: vi.fn(), boxOptions: vi.fn() }
})

import * as client from './client.ts'
import type { BoxTokenManager } from './client.ts'
import { eventsNow, eventsSince, realtimeServer } from './api.ts'

const TM = { apiBase: 'https://api.box.com/2.0' } as BoxTokenManager

beforeEach(() => {
  vi.clearAllMocks()
})

describe('box events api', () => {
  it('reads events until an empty page', async () => {
    // Box may return a short page while more events remain, so only an
    // empty page ends the read.
    vi.mocked(client.boxGet)
      .mockResolvedValueOnce({
        chunk_size: 1,
        next_stream_position: 11,
        entries: [{ event_id: 'a' }],
      })
      .mockResolvedValueOnce({
        chunk_size: 1,
        next_stream_position: '12',
        entries: [{ event_id: 'b' }],
      })
      .mockResolvedValueOnce({ chunk_size: 0, next_stream_position: '12', entries: [] })
    const found = await eventsSince(TM, '10', 'changes')
    expect(found.entries.map((e) => e.event_id)).toEqual(['a', 'b'])
    expect(found.position).toBe('12')
    const calls = vi.mocked(client.boxGet).mock.calls
    expect(calls.map((c) => c[2]?.stream_position)).toEqual(['10', '11', '12'])
    expect(calls[0]?.[1]).toBe('https://api.box.com/2.0/events')
    expect(calls[0]?.[2]?.stream_type).toBe('changes')
  })

  it('returns the stream head for now', async () => {
    vi.mocked(client.boxGet).mockResolvedValueOnce({
      chunk_size: 0,
      next_stream_position: '1152922976252290886',
      entries: [],
    })
    expect(await eventsNow(TM, 'changes')).toBe('1152922976252290886')
    expect(vi.mocked(client.boxGet).mock.calls[0]?.[2]?.stream_position).toBe('now')
  })

  it('asks OPTIONS /events for the long-poll server', async () => {
    const server = {
      type: 'realtime_server',
      url: 'http://2.realtime.services.box.net/subscribe?channel=c',
      ttl: '10',
      max_retries: '10',
      retry_timeout: 610,
    }
    vi.mocked(client.boxOptions).mockResolvedValueOnce({ chunk_size: 1, entries: [server] })
    expect((await realtimeServer(TM)).url).toBe(server.url)
    expect(vi.mocked(client.boxOptions).mock.calls[0]?.[1]).toBe('https://api.box.com/2.0/events')
  })

  it.each([null, '10', 10])('refuses events that do not advance (%s)', async (stuck) => {
    vi.mocked(client.boxGet).mockResolvedValueOnce({
      chunk_size: 1,
      next_stream_position: stuck,
      entries: [{ event_id: 'a' }],
    })
    await expect(eventsSince(TM, '10', 'changes')).rejects.toThrow('did not advance')
  })

  it('keeps its position on an empty page without one', async () => {
    vi.mocked(client.boxGet)
      .mockResolvedValueOnce({
        chunk_size: 1,
        next_stream_position: '11',
        entries: [{ event_id: 'a' }],
      })
      .mockResolvedValueOnce({ chunk_size: 0, entries: [] })
    const found = await eventsSince(TM, '10', 'changes')
    expect(found.entries.map((e) => e.event_id)).toEqual(['a'])
    expect(found.position).toBe('11')
  })

  it('refuses a stream head without a position', async () => {
    vi.mocked(client.boxGet).mockResolvedValueOnce({ chunk_size: 0, entries: [] })
    await expect(eventsNow(TM, 'changes')).rejects.toThrow('next_stream_position')
  })

  it('refuses an OPTIONS answer without a realtime server', async () => {
    vi.mocked(client.boxOptions).mockResolvedValueOnce({ chunk_size: 0 })
    await expect(realtimeServer(TM)).rejects.toThrow('realtime server')
  })
})
