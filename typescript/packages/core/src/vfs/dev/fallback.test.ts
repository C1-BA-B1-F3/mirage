import type * as AsyncContext from '../../utils/async_context.ts'
import { expect, it, vi } from 'vitest'

vi.mock('../../utils/async_context.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof AsyncContext>()
  return { ...actual, createAsyncContext: () => new actual.FallbackStorage() }
})

import { runWithSession } from '../../context/session_context.ts'
import { SessionState } from '../../workspace/session/session.ts'
import { DevFiles } from './store.ts'

it('refuses descriptor access when fallback contexts overlap', async () => {
  const files = new DevFiles()
  let readyResolve!: () => void
  const ready = new Promise<void>((resolve) => {
    readyResolve = resolve
  })
  let doneResolve!: () => void
  const done = new Promise<void>((resolve) => {
    doneResolve = resolve
  })
  const secret = new TextEncoder().encode('private')
  const owner = runWithSession(new SessionState({ sessionId: 'owner' }), async () => {
    const [path, allocation] = files.allocateInput()
    files.set(path.slice(4), secret)
    readyResolve()
    await done
    expect(files.get(path.slice(4))).toEqual(secret)
    files.releaseInput(path, allocation)
  })
  await ready
  try {
    await runWithSession(new SessionState({ sessionId: 'peer' }), () => {
      expect(files.has('/fd/63')).toBe(false)
      expect(files.get('/fd/63')).toBeUndefined()
      expect([...files.keys()]).not.toContain('/fd/63')
      expect(() => files.set('/fd/63', new Uint8Array())).toThrow()
      expect(files.delete('/fd/63')).toBe(false)
      expect(() => files.allocateInput()).toThrow()
      return Promise.resolve()
    })
  } finally {
    doneResolve()
    await owner
  }
  expect(files.get('/fd/63')).toBeUndefined()
})
