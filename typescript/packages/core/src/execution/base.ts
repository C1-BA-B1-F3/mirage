import type { ExecutionRecord } from './types.ts'

/**
 * Async request tracking; live work stays with the execution owner.
 *
 * Records are independent snapshots. Revisions increase on successful CAS.
 * Implementations may expire completed records, never active executions.
 */
export abstract class ExecutionStore {
  /** Insert once; false means the id already exists. */
  abstract create(record: ExecutionRecord): Promise<boolean>
  abstract get(id: string): Promise<ExecutionRecord | null>
  /** Records without their results; `get` returns one in full. */
  abstract list(workspaceId?: string): Promise<ExecutionRecord[]>
  /** Replace iff revision matches; the replacement has revision + 1. */
  abstract compareAndSet(record: ExecutionRecord, revision: number): Promise<boolean>
  /**
   * Return the changed or current record, null once it has expired.
   *
   * A wait observes a revision, so a change made before it registered is
   * not lost. `signal` ends it early with the current record, as a timeout
   * does.
   */
  abstract waitForChange(
    id: string,
    revision: number,
    timeoutSeconds?: number,
    signal?: AbortSignal,
  ): Promise<ExecutionRecord | null>
  abstract close(): Promise<void>
}
