import type { ExecutionRecord } from './types.ts'

/** Async request tracking. Live tasks/controllers stay with the execution owner. */
export abstract class ExecutionStore {
  /** Insert once; false means the id already exists. */
  abstract create(record: ExecutionRecord): Promise<boolean>
  abstract get(id: string): Promise<ExecutionRecord | null>
  abstract list(workspaceId?: string): Promise<ExecutionRecord[]>
  /** Replace iff revision matches; the replacement has revision + 1. */
  abstract compareAndSet(record: ExecutionRecord, revision: number): Promise<boolean>
  /** Observe revisions, including changes made before the wait was registered. */
  abstract waitForChange(
    id: string,
    revision: number,
    timeoutSeconds?: number,
  ): Promise<ExecutionRecord | null>
  abstract close(): Promise<void>
}
