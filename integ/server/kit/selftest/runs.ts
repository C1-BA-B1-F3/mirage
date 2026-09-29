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

import assert from 'node:assert/strict'
import { existsSync, readdirSync } from 'node:fs'
import { clearTenants } from '../typescript/clear.ts'
import { parseConfig } from '../typescript/config.ts'
import { start } from '../typescript/serve.ts'
import { resolveIdentity } from '../typescript/tenant.ts'
import { Router } from '../typescript/route.ts'
import type { Dmmf } from '../typescript/seed.ts'
import { selftestFake } from './fake.ts'

const PATTERN = '^draw:(?<run>[^:]+):(?<tenant>[^:]+)$'

function gate(): { wait: Promise<void>; release: () => void } {
  let release = (): void => {
    throw new Error('gate not initialized')
  }
  const wait = new Promise<void>((resolve) => {
    release = resolve
  })
  return { wait, release }
}

export async function runLifecycleTests(): Promise<void> {
  const config = parseConfig({
    ...selftestFake.config,
    runTokenPattern: PATTERN,
    tenantFromBearer: true,
  })
  const url = new URL('http://fake/boards')
  assert.deepEqual(resolveIdentity(config, { authorization: 'Bearer draw:a:ws' }, url), {
    run: 'a',
    tenant: 'ws',
  })
  assert.deepEqual(resolveIdentity(config, { authorization: 'token draw:a:ws' }, url), {
    run: 'a',
    tenant: 'ws',
  })
  assert.deepEqual(resolveIdentity(config, {}, url, undefined, 'draw:a:ws'), {
    run: 'a',
    tenant: 'ws',
  })
  assert.deepEqual(resolveIdentity(config, { authorization: 'Bearer ws' }, url), {
    run: 'default',
    tenant: 'ws',
  })
  assert.deepEqual(
    resolveIdentity(
      config,
      { authorization: 'Bearer draw:a:ws', 'x-mirage-run': 'b', 'x-mirage-tenant': 'other' },
      url,
      'path',
    ),
    { run: 'path', tenant: 'other' },
  )
  assert.deepEqual(
    resolveIdentity(
      config,
      { authorization: 'Bearer draw:a:ws' },
      new URL('http://fake/boards?_run=q&_tenant=t'),
    ),
    { run: 'q', tenant: 't' },
  )
  assert.throws(() => resolveIdentity(config, { authorization: 'Bearer draw:../bad:ws' }, url))
  assert.throws(() => parseConfig({ ...config, runTokenPattern: null }))
  assert.throws(() => parseConfig({ ...config, runTokenPattern: '[(?<run>)]' }))
  assert.throws(() => parseConfig({ ...config, runTokenPattern: '(' }))
  assert.throws(() => parseConfig({ ...config, runTokenPattern: '(.*)' }))
  assert.deepEqual(
    resolveIdentity({ ...config, runTokenPattern: '' }, { authorization: 'Bearer draw:a:ws' }, url),
    { run: 'default', tenant: 'default' },
  )

  const started = await start({ ...selftestFake, config }, 0, 'alt')
  const { runtime, endpoint } = started
  try {
    await runtime.reset({ run: 'a', tenants: ['ws'], fixture: 'v1' })
    const a = await fetch(`${endpoint}/boards/brd_1/cards`, {
      headers: { authorization: 'Bearer draw:a:ws' },
    })
    assert.equal(a.status, 200)
    assert.equal(((await a.json()) as { cards: unknown[] }).cards.length, 3)
    const b = await runtime.reset({ run: 'b', tenants: ['ws'] })
    assert.equal(b.seeded[0]?.rows.Card, 1, 'new run uses startup fixture')
    assert.equal((await runtime.reset({ run: 'a', tenants: ['ws'] })).seeded[0]?.rows.Card, 3)
    await assert.rejects(runtime.reset({ run: 'a', fixture: 'missing' }))
    assert.equal((await runtime.reset({ run: 'a', tenants: ['ws'] })).seeded[0]?.rows.Card, 3)
    const health = await (await fetch(`${endpoint}/_kit/health`)).json()
    assert.deepEqual(health, { ok: true, service: 'selftest', runs: 3 })

    const oldState = runtime.state('a')
    const oldClient = runtime.pool.client('a')
    const entered = gate()
    const release = gate()
    const reading = runtime.router.read('a', async () => {
      entered.release()
      await release.wait
      assert.equal(await oldClient.card.count({ where: { tenant: 'ws' } }), 3)
    })
    await entered.wait
    const dropping = runtime.drop('a')
    assert(existsSync(runtime.pool.fileFor('a')))
    release.release()
    await Promise.all([reading, dropping])
    assert(!runtime.pool.has('a'))
    assert(!readdirSync(runtime.pool.root).some((f) => f.startsWith('a.db')))
    assert.notEqual(runtime.state('a'), oldState)
    assert.equal(
      (await runtime.reset({ run: 'a', tenants: ['ws'] })).seeded[0]?.rows.Card,
      1,
      'drop forgets fixture',
    )
    assert.notEqual(runtime.pool.client('a'), oldClient)
    const deleted = await fetch(`${endpoint}/_kit/runs/a`, { method: 'DELETE' })
    assert.equal(deleted.status, 204)
    assert.equal((await fetch(`${endpoint}/_kit/runs/a`, { method: 'DELETE' })).status, 204)
    assert.equal(
      (await fetch(`${endpoint}/_kit/runs/bad%2Fname`, { method: 'DELETE' })).status,
      400,
    )
    assert.equal(await runtime.pool.client('b').card.count({ where: { tenant: 'ws' } }), 1)

    const releaseWrite = gate()
    const writing = runtime.router.enqueue('b', () => releaseWrite.wait)
    const resetting = runtime.reset({ run: 'b', tenants: ['ws'], fixture: 'v1' })
    const dropAfterReset = runtime.drop('b')
    releaseWrite.release()
    await Promise.all([writing, resetting, dropAfterReset])
    assert(!runtime.pool.has('b'), 'drop follows writes and reset')
    assert.equal(
      readdirSync(`${runtime.pool.root}/.templates`).filter((f) => f.startsWith('seeded-')).length,
      1,
      'only the default run retains its seed template',
    )
    await Promise.all(
      ['shared-a', 'shared-b'].map((run) => runtime.reset({ run, tenants: ['shared'] })),
    )
    await runtime.drop('shared-a')
    assert.equal(await runtime.pool.client('shared-b').card.count(), 1)
    await runtime.drop('shared-b')
    assert.equal(
      readdirSync(`${runtime.pool.root}/.templates`).filter((f) => f.startsWith('seeded-')).length,
      1,
    )
  } finally {
    await started.close()
  }

  const router = new Router<never>([])
  const release = gate()
  const entered = gate()
  const first = router.read('a', async () => {
    entered.release()
    await release.wait
  })
  await entered.wait
  await router.read('a', () => undefined) // reads run concurrently
  const pending = router.enqueue('a', () => undefined)
  await router.enqueue('b', () => undefined) // other runs do not wait
  release.release()
  await Promise.all([first, pending])
  await assert.rejects(
    router.enqueue('a', () => {
      throw new Error('expected')
    }),
  )
  await router.enqueue('a', () => undefined)

  const statements: [string, string[]][] = []
  const mapped: Dmmf = {
    datamodel: {
      models: [
        {
          name: 'Model',
          dbName: 'table"name',
          fields: [
            {
              name: 'tenant',
              dbName: 'tenant"name',
              kind: 'scalar',
              type: 'String',
              isList: false,
            },
          ],
        },
      ],
    },
  }
  assert.equal(
    await clearTenants(
      {
        $executeRawUnsafe: async (sql: string, ...values: string[]) => {
          statements.push([sql, values])
          return 2
        },
      },
      mapped,
      ["a' OR 1=1 --"],
    ),
    2,
  )
  assert.deepEqual(statements, [
    ['DELETE FROM "table""name" WHERE "tenant""name" = ?', ["a' OR 1=1 --"]],
  ])
  process.stdout.write('run lifecycle regressions passed\n')
}
