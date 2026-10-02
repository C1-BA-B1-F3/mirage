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
import { JobStatus, JobTable, newJobId } from './jobs.ts'

describe('newJobId', () => {
  it('mints job_<hex16> ids', () => {
    expect(newJobId()).toMatch(/^job_[a-f0-9]{16}$/)
  })
})

describe('JobTable', () => {
  it('submit -> done flow', async () => {
    const table = new JobTable()
    const entry = table.submit('ws1', 'echo hi', () => Promise.resolve('result-value'))
    expect(entry.status).toBe(JobStatus.RUNNING)
    const finished = await table.wait(entry.id)
    expect(finished.status).toBe(JobStatus.DONE)
    expect(finished.result).toBe('result-value')
  })

  it('captures rejection and a synchronous throw as FAILED', async () => {
    const table = new JobTable()
    const entry = table.submit('ws1', 'boom', () => Promise.reject(new Error('boom')))
    const finished = await table.wait(entry.id)
    expect(finished.status).toBe(JobStatus.FAILED)
    expect(finished.error).toContain('boom')
    const thrown = table.submit('ws1', 'sync', () => {
      throw new Error('synchronous failure')
    })
    expect(thrown.status).toBe(JobStatus.FAILED)
  })

  it('list filtered by workspace_id', () => {
    const table = new JobTable()
    table.submit('a', 'x', () => Promise.resolve(null))
    table.submit('b', 'y', () => Promise.resolve(null))
    expect(table.list('a')).toHaveLength(1)
    expect(table.list()).toHaveLength(2)
  })

  it('wait timeout returns still-running entry', async () => {
    const table = new JobTable()
    const entry = table.submit('ws1', 'slow', () => new Promise(() => undefined))
    const result = await table.wait(entry.id, 0.01)
    expect(result.status).toBe(JobStatus.RUNNING)
  })

  it('cancel aborts the coroutine and reports only after its cleanup settles', async () => {
    let started!: () => void
    let release!: () => void
    const cleanup = new Promise<void>((resolve) => {
      started = resolve
    })
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const table = new JobTable()
    const job = table.submit('ws', 'probe', async (signal) => {
      try {
        await new Promise<void>((_, reject) => {
          signal.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        })
      } finally {
        started()
        await gate
      }
    })
    expect(table.cancel(job.id)).toBe(true)
    await cleanup
    expect(job.finishedAt).toBeNull()
    expect(job.status).toBe(JobStatus.RUNNING)
    expect(table.cancel(job.id)).toBe(false)
    release()
    expect((await table.wait(job.id)).status).toBe(JobStatus.CANCELED)
  })

  it('bounds completed retention without evicting active jobs', async () => {
    const table = new JobTable(2, 10)
    let release!: () => void
    const active = table.submit(
      'ws',
      'active',
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        }),
    )
    const first = table.submit('ws', 'first', () => Promise.resolve('one'))
    await table.wait(first.id)
    for (const name of ['second', 'third']) {
      await table.wait(table.submit('ws', name, () => Promise.resolve(name)).id)
    }
    expect(table.has(first.id)).toBe(false)
    expect(table.has(active.id)).toBe(true)
    const last = table.list().at(-1)
    if (last?.finishedAt == null) throw new Error('job did not finish')
    const clock = vi.spyOn(Date, 'now').mockReturnValue((last.finishedAt + 11) * 1000)
    try {
      expect(table.list()).toEqual([active])
    } finally {
      clock.mockRestore()
    }
    release()
    await table.wait(active.id)
  })

  it('AbortError without abort signal still classifies as FAILED', async () => {
    const table = new JobTable()
    const job = table.submit('ws-1', 'weird', () =>
      Promise.reject(new DOMException('unrelated abort', 'AbortError')),
    )
    const entry = await table.wait(job.id)
    expect(entry.status).toBe(JobStatus.FAILED)
  })
})
