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

import { newWorkspaceId } from '@struktoai/mirage-core/utils/ids'
import { WorkspaceRunner } from '@struktoai/mirage-core/workspace/runner'
import type { Workspace } from '@struktoai/mirage-node'

export class WorkspaceEntry {
  readonly id: string
  readonly runner: WorkspaceRunner
  readonly createdAt: number

  constructor(id: string, runner: WorkspaceRunner) {
    this.id = id
    this.runner = runner
    this.createdAt = Date.now() / 1000
  }
}

export interface WorkspaceRegistryOptions {
  idleGraceSeconds?: number
  onIdleExit?: () => void
}

export class WorkspaceRegistry {
  private entries = new Map<string, WorkspaceEntry>()
  private readonly removals = new Map<string, Promise<WorkspaceEntry>>()
  private readonly idleGraceSeconds: number
  private readonly onIdleExit: (() => void) | null
  private idleTimer: NodeJS.Timeout | null = null

  constructor(options: WorkspaceRegistryOptions = {}) {
    this.idleGraceSeconds = options.idleGraceSeconds ?? 30
    this.onIdleExit = options.onIdleExit ?? null
  }

  has(id: string): boolean {
    return this.entries.has(id)
  }

  get(id: string): WorkspaceEntry {
    const e = this.entries.get(id)
    if (e === undefined) throw new Error(`workspace not found: ${id}`)
    return e
  }

  list(): WorkspaceEntry[] {
    return Array.from(this.entries.values())
  }

  size(): number {
    return this.entries.size
  }

  add(ws: Workspace, id?: string): WorkspaceEntry {
    const wid = id ?? newWorkspaceId()
    if (this.entries.has(wid)) throw new Error(`workspace id already exists: ${wid}`)
    const entry = new WorkspaceEntry(wid, new WorkspaceRunner(ws))
    this.entries.set(wid, entry)
    this.cancelIdleTimer()
    return entry
  }

  /**
   * Delete `id`: stop its runner and drop its state. The workspace's
   * links, history, sessions and metadata leave its state store with it,
   * so a workspace created later under the same id starts empty.
   * `closeAll` (daemon shutdown) keeps them. The id stays registered
   * until the deletion is done, so a create under it is refused rather
   * than registering a workspace whose state this deletion would then
   * remove; `cleanup` runs inside that window. An overlapping remove of
   * the same id joins the deletion in flight, so it never unregisters a
   * workspace created after it.
   */
  async remove(id: string, cleanup?: () => Promise<void>): Promise<WorkspaceEntry> {
    let removal = this.removals.get(id)
    if (removal === undefined) {
      const entry = this.entries.get(id)
      if (entry === undefined) throw new Error(`workspace not found: ${id}`)
      removal = this.drop(entry, cleanup)
      this.removals.set(id, removal)
    }
    return removal
  }

  /** Run one deletion, releasing the id once it is done. */
  private async drop(
    entry: WorkspaceEntry,
    cleanup?: () => Promise<void>,
  ): Promise<WorkspaceEntry> {
    try {
      await entry.runner.stop({ delete: true })
      if (cleanup !== undefined) await cleanup()
    } finally {
      this.removals.delete(entry.id)
      this.entries.delete(entry.id)
      if (this.entries.size === 0) this.startIdleTimer()
    }
    return entry
  }

  async closeAll(): Promise<void> {
    this.cancelIdleTimer()
    const ids = Array.from(this.entries.keys())
    for (const id of ids) {
      const entry = this.entries.get(id)
      this.entries.delete(id)
      if (entry !== undefined) await entry.runner.stop()
    }
  }

  private startIdleTimer(): void {
    if (this.onIdleExit === null) return
    if (this.idleGraceSeconds <= 0) {
      this.onIdleExit()
      return
    }
    if (this.idleTimer !== null) return
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null
      if (this.entries.size === 0 && this.onIdleExit !== null) this.onIdleExit()
    }, this.idleGraceSeconds * 1000)
  }

  private cancelIdleTimer(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer)
      this.idleTimer = null
    }
  }
}
