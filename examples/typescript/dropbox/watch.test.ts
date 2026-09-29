import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Delta, FileEvent, FileChangeKind, PathSpec } from '@struktoai/mirage-core/types'
import { cursorOf, longpoll, runLongpoll } from './watch.ts'

const checkpoint = (c: string): string => JSON.stringify({ _dbx: 1, c, s: { '/dropbox/a': 'old' } })

test('longpoll refreshes its cursor after every pull and honors idle backoff', async () => {
  const calls: (string | number)[][] = []
  const checkpoints: (string | null)[] = []
  const states = ['a', 'b', 'c'].map(checkpoint)
  const stop = new Error('stop')
  await assert.rejects(
    runLongpoll(
      {
        pull: async (_root, previous) => {
          checkpoints.push(previous)
          return new Delta({ changes: [], checkpoint: states[checkpoints.length - 1]! })
        },
      },
      PathSpec.fromStrPath('/dropbox', ''),
      async () => {
        assert.fail('unexpected event')
      },
      async (cursor) => {
        calls.push(['poll', cursor])
        if (calls.length === 1) return [false, 5]
        if (cursor === 'a') return [true, 2]
        if (cursor === 'b') return [true, 0]
        throw stop
      },
      async (seconds) => {
        calls.push(['pause', seconds])
      },
    ),
    (error) => error === stop,
  )
  assert.deepEqual(calls, [
    ['poll', 'a'],
    ['pause', 5],
    ['poll', 'a'],
    ['pause', 2],
    ['poll', 'b'],
    ['poll', 'c'],
  ])
  assert.deepEqual(checkpoints, [null, ...states.slice(0, 2)])
})

test('longpoll sends no authorization and treats reset as a pull with the old checkpoint', async (t) => {
  const calls: RequestInit[] = []
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, 'https://notify.dropboxapi.com/2/files/list_folder/longpoll')
    calls.push(options)
    return new Response(JSON.stringify({ error: { '.tag': 'reset' } }), { status: 409 })
  })
  assert.deepEqual(await longpoll('cursor', new AbortController().signal), [true, 0])
  assert.deepEqual(calls[0]!.headers, { 'Content-Type': 'application/json' })
  assert.deepEqual(JSON.parse(calls[0]!.body as string), { cursor: 'cursor', timeout: 30 })
})

test('unsupported checkpoint versions fail loudly', () => {
  assert.throws(() => cursorOf('{"_dbx":2,"c":"a"}'), /Unsupported/)
})

test('a missing root retries, preserves its snapshot, and notifies before polling', async () => {
  const root = PathSpec.fromStrPath('/dropbox', '')
  const change = new FileEvent({
    kind: FileChangeKind.CREATE,
    path: PathSpec.fromStrPath('/dropbox/a'),
    timestamp: new Date(0),
  })
  const states = [
    new Delta({ changes: [], checkpoint: '{}' }),
    new Delta({ changes: [change], checkpoint: checkpoint('recovered') }),
  ]
  const calls: unknown[] = []
  const stop = new Error('stop')
  await assert.rejects(
    runLongpoll(
      {
        pull: async (_root, previous) => {
          calls.push(['pull', previous])
          return states.shift()!
        },
      },
      root,
      async (event) => {
        calls.push(['notify', event])
      },
      async (cursor) => {
        calls.push(['poll', cursor])
        throw stop
      },
      async (seconds) => {
        calls.push(['pause', seconds])
      },
    ),
    (error) => error === stop,
  )
  assert.deepEqual(calls, [
    ['pull', null],
    ['pause', 30],
    ['pull', '{}'],
    ['notify', change],
    ['poll', 'recovered'],
  ])
})
