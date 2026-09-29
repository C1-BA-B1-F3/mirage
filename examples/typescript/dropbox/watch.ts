/** Consumer-owned Dropbox longpoll -> cursor pull -> workspace notification.
 * Set DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN, and optionally
 * DROPBOX_ROOT_PATH. From typescript/, run pnpm --filter @struktoai/mirage-examples exec tsx dropbox/watch.ts. Ctrl-C stops it.
 */
import { setTimeout as delay } from 'node:timers/promises'
import { pathToFileURL } from 'node:url'
import { DropboxVFS, PathSpec, Workspace, type FileEvent } from '@struktoai/mirage-node'
import type { DeltaHook } from '@struktoai/mirage-core/watch/base'

const MOUNT = '/dropbox'
const LONGPOLL_URL = 'https://notify.dropboxapi.com/2/files/list_folder/longpoll'
const TIMEOUT = 30 // Dropbox permits 30..480 seconds, plus up to 90s of jitter.

export function cursorOf(checkpoint: string | null): string | null {
  // This example knows Dropbox's v1 envelope. Keep the entire checkpoint for
  // pull, including its last applied snapshot, instead of storing just a cursor.
  const data: unknown = checkpoint === null ? {} : JSON.parse(checkpoint)
  if (data === null || typeof data !== 'object')
    throw new Error('Expected a Dropbox checkpoint object')
  if (!('_dbx' in data)) return null // Missing root: a listing snapshot.
  if (data._dbx !== 1 || !('c' in data) || typeof data.c !== 'string')
    throw new Error('Unsupported Dropbox checkpoint format')
  return data.c || null
}

export async function longpoll(cursor: string, signal: AbortSignal): Promise<[boolean, number]> {
  // No Authorization header: the cursor is sufficient. Allow server jitter.
  const response = await fetch(LONGPOLL_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cursor, timeout: TIMEOUT }),
    signal: AbortSignal.any([signal, AbortSignal.timeout((TIMEOUT + 100) * 1000)]),
  })
  const result = (await response.json()) as {
    changes: boolean
    backoff?: number
    error?: { '.tag'?: string }
  }
  if (response.status === 409 && result.error?.['.tag'] === 'reset') return [true, 0]
  if (!response.ok) throw new Error(`Dropbox longpoll HTTP ${response.status}`)
  return [result.changes, result.backoff ?? 0]
}

export async function runLongpoll(
  hook: DeltaHook,
  root: PathSpec,
  notify: (change: FileEvent) => Promise<void>,
  poll: (cursor: string) => Promise<[boolean, number]>,
  pause: (seconds: number) => Promise<void>,
): Promise<void> {
  let checkpoint = (await hook.pull(root, null)).checkpoint
  for (;;) {
    const cursor = cursorOf(checkpoint) // Pull may replace it even without events.
    let changed: boolean
    let backoff: number
    if (cursor === null) {
      await pause(TIMEOUT) // Bounded retry while the root is unavailable.
      changed = true
      backoff = 0
    } else {
      ;[changed, backoff] = await poll(cursor)
    }
    if (changed) {
      // Preserve the old snapshot on reset; the existing hook relists and diffs.
      const delta = await hook.pull(root, checkpoint)
      for (const change of delta.changes) await notify(change)
      checkpoint = delta.checkpoint
    }
    if (backoff) await pause(backoff) // Required even when changes == false.
  }
}

async function main(): Promise<void> {
  const clientId = process.env.DROPBOX_APP_KEY
  const clientSecret = process.env.DROPBOX_APP_SECRET
  const refreshToken = process.env.DROPBOX_REFRESH_TOKEN
  if (!clientId || !clientSecret || !refreshToken)
    throw new Error('Set the three DROPBOX credentials')
  const vfs = new DropboxVFS({
    clientId,
    clientSecret,
    refreshToken,
    rootPath: process.env.DROPBOX_ROOT_PATH || '/',
  })
  const ws = new Workspace({ [MOUNT]: vfs })
  const controller = new AbortController()
  const stop = (): void => controller.abort()
  process.once('SIGINT', stop)
  try {
    console.log(`Watching ${MOUNT}; edit files in Dropbox (Ctrl-C to stop)`)
    await runLongpoll(
      vfs.deltaHook(),
      PathSpec.fromStrPath(MOUNT, ''),
      async (change) => {
        await ws.notify(change)
        console.log(`${change.kind}: ${change.path.virtual}`)
      },
      (cursor) => longpoll(cursor, controller.signal),
      async (seconds) => {
        await delay(seconds * 1000, undefined, { signal: controller.signal })
      },
    )
  } catch (error) {
    if (!controller.signal.aborted) throw error
  } finally {
    process.removeListener('SIGINT', stop)
    await ws.close()
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main()
}
