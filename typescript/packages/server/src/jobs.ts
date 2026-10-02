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

import { randomBytes } from 'node:crypto'

export const JobStatus = Object.freeze({
  PENDING: 'pending',
  RUNNING: 'running',
  DONE: 'done',
  FAILED: 'failed',
  CANCELED: 'canceled',
} as const)
export type JobStatus = (typeof JobStatus)[keyof typeof JobStatus]

export function newJobId(): string {
  return `job_${randomBytes(8).toString('hex')}`
}

export class JobEntry {
  readonly id: string
  readonly workspaceId: string
  readonly command: string
  readonly controller: AbortController = new AbortController()
  status: JobStatus = JobStatus.PENDING
  result: unknown = null
  error: string | null = null
  readonly submittedAt: number = Date.now() / 1000
  startedAt: number | null = null
  finishedAt: number | null = null
  readonly done: Promise<void>
  private resolveDone!: () => void

  constructor(id: string, workspaceId: string, command: string) {
    this.id = id
    this.workspaceId = workspaceId
    this.command = command
    this.done = new Promise((resolve) => {
      this.resolveDone = resolve
    })
  }

  markFinished(): void {
    this.finishedAt = Date.now() / 1000
    this.resolveDone()
  }
}

/** Keep at most 1024 completed jobs; expire them after one hour on access/completion. */
export class JobTable {
  private jobs = new Map<string, JobEntry>()
  private completed = new Map<string, JobEntry>()

  constructor(
    private readonly maxCompleted = 1024,
    private readonly retentionSeconds = 3600,
  ) {
    if (maxCompleted < 1 || retentionSeconds <= 0)
      throw new Error('job retention limits must be positive')
  }

  private prune(): void {
    const cutoff = Date.now() / 1000 - this.retentionSeconds
    for (const [id, job] of this.completed) {
      if (
        this.completed.size <= this.maxCompleted &&
        job.finishedAt !== null &&
        job.finishedAt > cutoff
      )
        break
      this.completed.delete(id)
      this.jobs.delete(id)
    }
  }

  has(id: string): boolean {
    this.prune()
    return this.jobs.has(id)
  }

  get(id: string): JobEntry {
    this.prune()
    const entry = this.jobs.get(id)
    if (entry === undefined) throw new Error(`job not found: ${id}`)
    return entry
  }

  list(workspaceId?: string): JobEntry[] {
    this.prune()
    const all = Array.from(this.jobs.values())
    if (workspaceId === undefined) return all
    return all.filter((j) => j.workspaceId === workspaceId)
  }

  submit(
    workspaceId: string,
    command: string,
    coroFactory: (signal: AbortSignal) => Promise<unknown>,
  ): JobEntry {
    this.prune()
    const entry = new JobEntry(newJobId(), workspaceId, command)
    this.jobs.set(entry.id, entry)
    entry.status = JobStatus.RUNNING
    entry.startedAt = Date.now() / 1000
    void this.run(entry, coroFactory)
    return entry
  }

  private async run(
    entry: JobEntry,
    factory: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<void> {
    try {
      entry.result = await factory(entry.controller.signal)
      entry.status = JobStatus.DONE
    } catch (err) {
      entry.status = JobStatus.FAILED
      entry.error = err instanceof Error ? `${err.name}: ${err.message}` : String(err)
    } finally {
      if (entry.controller.signal.aborted) {
        entry.status = JobStatus.CANCELED
        entry.result = null
      }
      entry.markFinished()
      this.completed.set(entry.id, entry)
      this.prune()
    }
  }

  async wait(id: string, timeoutSeconds?: number): Promise<JobEntry> {
    const entry = this.get(id)
    if (entry.finishedAt !== null) return entry
    if (timeoutSeconds === undefined) {
      await entry.done
      return entry
    }
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      await Promise.race([
        entry.done,
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, timeoutSeconds * 1000)
        }),
      ])
    } finally {
      clearTimeout(timer)
    }
    return entry
  }

  cancel(id: string): boolean {
    const entry = this.get(id)
    if (entry.finishedAt !== null) {
      return false
    }
    if (entry.controller.signal.aborted) return false
    entry.controller.abort()
    return true
  }
}

export interface JobBriefDict {
  jobId: string
  workspaceId: string
  command: string
  status: JobStatus
  submittedAt: number
  startedAt: number | null
  finishedAt: number | null
}

export function toBriefDict(entry: JobEntry): JobBriefDict {
  return {
    jobId: entry.id,
    workspaceId: entry.workspaceId,
    command: entry.command,
    status: entry.status,
    submittedAt: entry.submittedAt,
    startedAt: entry.startedAt,
    finishedAt: entry.finishedAt,
  }
}
